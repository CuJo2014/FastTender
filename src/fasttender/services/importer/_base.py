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


def validate_and_dedupe(items: list[ParsedItem], report: ImportReport) -> list[ParsedItem]:
    """Отсеивает строки без имени и дубли артикулов внутри файла.

    Дубликат = две строки с одинаковым `article_normalized` (не NULL).
    Оставляем первую, остальные попадают в report.duplicates как мягкое
    предупреждение (раздел 16.3 пункт 2: «не падать»).
    """
    seen: dict[str, int] = {}  # article_normalized → line_number
    duplicates: dict[str, list[int]] = {}
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

        article_norm = normalize_article(item.article)
        if article_norm is not None:
            if article_norm in seen:
                duplicates.setdefault(article_norm, []).append(item.line_number)
                report.rows_skipped += 1
                continue
            seen[article_norm] = item.line_number

        valid.append(item)

    report.duplicates = [
        DuplicateArticle(
            article=article,
            first_line=seen[article],
            duplicate_lines=lines,
        )
        for article, lines in duplicates.items()
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
        name=parsed.name,
        name_normalized=normalize_name(parsed.name),
        manufacturer=parsed.manufacturer,
        manufacturer_normalized=(parsed.manufacturer.lower() if parsed.manufacturer else None),
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
    """MERGE: обновляет существующие по article_normalized, новые INSERT.

    Возвращает (imported, updated).
    """
    articles = [a for a in (normalize_article(i.article) for i in items) if a is not None]
    existing: dict[str, Item] = {}
    if articles:
        stmt = select(Item).where(
            Item.source_id == source_id,
            Item.article_normalized.in_(articles),
        )
        for row in (await session.scalars(stmt)).all():
            if row.article_normalized:
                existing[row.article_normalized] = row

    imported = 0
    updated = 0
    for item in items:
        article_norm = normalize_article(item.article)
        target = existing.get(article_norm) if article_norm else None
        if target is not None:
            target.article_raw = item.article
            target.name = item.name
            target.name_normalized = normalize_name(item.name)
            target.manufacturer = item.manufacturer
            target.manufacturer_normalized = (
                item.manufacturer.lower() if item.manufacturer else None
            )
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
