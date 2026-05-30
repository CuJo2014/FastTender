"""Общая логика импорта Item-ов (каталог и прайсы).

Каталог компании и прайсы поставщиков различаются только источником
(`DataSource.type`), но данные грузятся в одну таблицу ITEM (раздел 8.2).
Поэтому код валидации, дедупликации, REPLACE/MERGE-режимов — общий.

Каталог-специфичные и прайс-специфичные хедеры лежат в соответствующих
модулях (catalog.py, pricelist.py) и зовут функции отсюда.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import DataSource, Item
from fasttender.services.importer.types import (
    DuplicateArticle,
    ImportMode,
    ImportReport,
    RowError,
)
from fasttender.services.parser import ParsedItem
from fasttender.services.parser.value_normalizer import normalize_article, normalize_name


def now_utc() -> datetime:
    return datetime.now(UTC)


def _dedupe_key(item: ParsedItem) -> tuple[str, str] | None:
    """Возвращает (тег, ключ) для дедупликации внутри файла.

    Приоритет (от более надёжного к менее):
      1. ("code", code_1c)              — если есть, primary identity 1С
      2. ("article+brand", art|brand)   — артикул в паре с брендом, разные
                                          бренды с тем же артикулом = разные товары
      3. ("article", art)               — только артикул, без бренда
      4. None                            — нет identifier, дедуп не делаем
    """
    if item.code_1c:
        return ("code", item.code_1c.strip())
    article_norm = normalize_article(item.article)
    if article_norm:
        if item.manufacturer:
            brand = item.manufacturer.strip().lower()
            return ("article+brand", f"{article_norm}|{brand}")
        return ("article", article_norm)
    return None


def _human_key_label(key_tuple: tuple[str, str]) -> str:
    """Для отчёта: человекочитаемое представление ключа дедупа."""
    tag, value = key_tuple
    if tag == "code":
        return f"Код 1С {value}"
    if tag == "article+brand":
        art, brand = value.split("|", 1)
        return f"{art} [{brand}]"
    return value


def validate_and_dedupe(items: list[ParsedItem], report: ImportReport) -> list[ParsedItem]:
    """Отсеивает строки без имени и дубли по composite ключу.

    Дубликат = две строки с одинаковым `_dedupe_key`. Composite ключ
    учитывает code_1c, либо пару (артикул + бренд), либо только артикул —
    одинаковые артикулы у РАЗНЫХ брендов теперь не считаются дубликатами
    (см. миграцию 0006).

    Оставляем первую, остальные попадают в report.duplicates как мягкое
    предупреждение (раздел 16.3 пункт 2: «не падать»).
    """
    seen: dict[tuple[str, str], int] = {}
    duplicates: dict[tuple[str, str], list[int]] = {}
    valid: list[ParsedItem] = []

    for item in items:
        if not item.name or not item.name.strip():
            report.errors.append(
                RowError(
                    line_number=item.line_number,
                    reason="empty_name",
                    raw=item.raw_row,
                )
            )
            report.rows_skipped += 1
            continue

        key = _dedupe_key(item)
        if key is None:
            # Нет identifier — каждая строка уникальна, не дедуплицируем
            valid.append(item)
            continue

        if key in seen:
            duplicates.setdefault(key, []).append(item.line_number)
            report.rows_skipped += 1
            continue
        seen[key] = item.line_number
        valid.append(item)

    report.duplicates = [
        DuplicateArticle(
            article=_human_key_label(key),
            first_line=seen[key],
            duplicate_lines=lines,
        )
        for key, lines in duplicates.items()
    ]
    return valid


def build_orm_item(source_id: UUID, parsed: ParsedItem) -> Item:
    """Маппинг ParsedItem → ORM Item.

    attributes остаётся {} — характеристики в Фазе 1 не извлекаются (раздел 4.2).
    """
    return Item(
        source_id=source_id,
        article_raw=parsed.article,
        article_normalized=normalize_article(parsed.article),
        code_1c=parsed.code_1c,
        name=parsed.name,
        name_normalized=normalize_name(parsed.name),
        manufacturer=parsed.manufacturer,
        manufacturer_normalized=(parsed.manufacturer.lower() if parsed.manufacturer else None),
        category_path=parsed.category,
        price=parsed.price,
        currency=parsed.currency,
        unit=parsed.unit,
        in_stock=True,
        attributes={},
        is_active=True,
    )


async def deactivate_existing(session: AsyncSession, source_id: UUID) -> int:
    """REPLACE: помечает все позиции источника is_active=false.

    Физическое удаление не делаем — на эти Item могут ссылаться MatchCandidate
    и Verification в истории. Деактивация исключает их из новых поисков
    (фильтр is_active=true в матчере).
    """
    result = await session.execute(
        update(Item).where(Item.source_id == source_id).values(is_active=False)
    )
    return result.rowcount or 0


async def upsert_items(
    session: AsyncSession,
    source_id: UUID,
    items: list[ParsedItem],
) -> tuple[int, int]:
    """MERGE: composite lookup. Существующие обновляются, новые INSERT.

    Lookup keys (приоритет такой же как в _dedupe_key):
      1. code_1c (когда есть) — primary identity 1С
      2. (article_normalized, manufacturer_normalized) — для не-1С источников
      3. article_normalized — fallback когда нет бренда

    Возвращает (imported, updated).
    """
    codes = [i.code_1c.strip() for i in items if i.code_1c]
    articles = [a for a in (normalize_article(i.article) for i in items) if a is not None]

    existing_by_code: dict[str, Item] = {}
    existing_by_art_brand: dict[tuple[str, str | None], Item] = {}

    # Lookup существующих позиций. Грузим всё что может пересечься, потом
    # маппим в Python — это и проще, и не требует hairy SQL для composite key.
    if codes:
        stmt = select(Item).where(Item.source_id == source_id, Item.code_1c.in_(codes))
        for row in (await session.scalars(stmt)).all():
            if row.code_1c:
                existing_by_code[row.code_1c] = row

    if articles:
        stmt = select(Item).where(
            Item.source_id == source_id,
            Item.article_normalized.in_(articles),
            Item.code_1c.is_(None),
        )
        for row in (await session.scalars(stmt)).all():
            if row.article_normalized:
                brand = (
                    row.manufacturer_normalized.strip().lower()
                    if row.manufacturer_normalized
                    else None
                )
                existing_by_art_brand[(row.article_normalized, brand)] = row

    imported = 0
    updated = 0
    for item in items:
        target: Item | None = None
        if item.code_1c:
            target = existing_by_code.get(item.code_1c.strip())
        else:
            article_norm = normalize_article(item.article)
            brand = item.manufacturer.strip().lower() if item.manufacturer else None
            if article_norm:
                target = existing_by_art_brand.get((article_norm, brand))

        if target is not None:
            target.article_raw = item.article
            target.code_1c = item.code_1c
            target.name = item.name
            target.name_normalized = normalize_name(item.name)
            target.manufacturer = item.manufacturer
            target.manufacturer_normalized = (
                item.manufacturer.lower() if item.manufacturer else None
            )
            target.category_path = item.category
            target.price = item.price
            target.currency = item.currency
            target.unit = item.unit
            target.is_active = True
            updated += 1
        else:
            session.add(build_orm_item(source_id, item))
            imported += 1
    return imported, updated


async def apply_to_source(
    session: AsyncSession,
    source: DataSource,
    parsed_items: list[ParsedItem],
    mode: ImportMode,
    report: ImportReport,
) -> None:
    """Применяет уже валидированные ParsedItem к источнику в выбранном режиме.

    Заполняет соответствующие поля report (rows_imported / rows_updated /
    rows_deactivated). Не выполняет commit — это ответственность вызывающего.
    """
    if mode is ImportMode.REPLACE:
        report.rows_deactivated = await deactivate_existing(session, source.id)
        for parsed in parsed_items:
            session.add(build_orm_item(source.id, parsed))
        report.rows_imported = len(parsed_items)
    elif mode is ImportMode.MERGE:
        imported, updated = await upsert_items(session, source.id, parsed_items)
        report.rows_imported = imported
        report.rows_updated = updated
    else:  # pragma: no cover — защита от расширения enum'а
        from fasttender.services.importer.types import ImportError

        raise ImportError(f"Неизвестный режим импорта: {mode}")

    source.last_synced_at = now_utc()
