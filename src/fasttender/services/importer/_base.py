"""Общая логика импорта Item-ов (каталог и прайсы).

Каталог компании и прайсы поставщиков различаются только источником
(`DataSource.type`), но данные грузятся в одну таблицу ITEM (раздел 8.2).
Поэтому код валидации, дедупликации, REPLACE/MERGE-режимов — общий.

Каталог-специфичные и прайс-специфичные хедеры лежат в соответствующих
модулях (catalog.py, pricelist.py) и зовут функции отсюда.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

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

# Макс. элементов в одном IN/NOT IN. PostgreSQL/asyncpg не допускает больше
# 32767 bind-параметров на запрос — на больших каталогах (>32767 строк)
# единый IN-список превышал лимит и ронял импорт с InterfaceError
# (инцидент 2026-06-05). Держим заметно ниже лимита: 1-2 параметра базового
# фильтра + чанк всё ещё умещается с запасом.
_PARAM_CHUNK = 10_000


def _chunked[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """Бьёт последовательность на чанки ≤ size — чтобы число bind-параметров
    в IN/NOT IN не превышало лимит PostgreSQL/asyncpg."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


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


def _item_dedupe_key(item: Item) -> tuple[str, str] | None:
    """Тот же composite-ключ что `_dedupe_key`, но для ORM Item.

    Нужен для сопоставления уже сохранённых позиций с входящими ParsedItem
    при пере-загрузке прайса — чтобы supplier_sku оставался стабильным.
    """
    if item.code_1c:
        return ("code", item.code_1c.strip())
    art = item.article_normalized
    if not art:
        return None
    if item.manufacturer_normalized:
        return ("article+brand", f"{art}|{item.manufacturer_normalized.strip().lower()}")
    if item.manufacturer:
        return ("article+brand", f"{art}|{item.manufacturer.strip().lower()}")
    return ("article", art)


async def auto_link_to_catalog(session: AsyncSession, source_id: UUID) -> int:
    """Для каждой активной pricelist-позиции находит карточку в каталоге
    компании и проставляет ссылку. Позиции с `catalog_link_source = 'manual'`
    не трогаем — выбор менеджера приоритетен.

    Lookup priority (как в _item_dedupe_key):
      1. code_1c (точное совпадение)
      2. (article_normalized, manufacturer_normalized.lower())
      3. article_normalized

    Bulk-loading: каталог загружается один раз в Python-словари — для прайса
    в 8K позиций и каталога в 100K это ~2 секунды против N запросов.

    Возвращает количество позиций которым удалось проставить (или обновить)
    ссылку.
    """
    from fasttender.models import DataSource, DataSourceType

    catalog_source_id = await session.scalar(
        select(DataSource.id).where(DataSource.type == DataSourceType.COMPANY_CATALOG)
    )
    if catalog_source_id is None:
        return 0  # каталог компании ещё не загружен — нечего связывать

    catalog_items = (
        await session.scalars(
            select(Item).where(
                Item.source_id == catalog_source_id,
                Item.is_active.is_(True),
            )
        )
    ).all()

    by_code: dict[str, Item] = {}
    by_art_brand: dict[tuple[str, str], Item] = {}
    by_art: dict[str, Item] = {}
    for c in catalog_items:
        if c.code_1c:
            by_code[c.code_1c.strip()] = c
        if c.article_normalized:
            if c.manufacturer_normalized:
                by_art_brand[(c.article_normalized, c.manufacturer_normalized.lower())] = c
            # by_art всегда регистрируем: фолбэк для прайсов без бренда.
            # Если несколько каталог-карточек делят article — берём первую
            # детерминированно (по итерации). Менеджер может переопределить вручную.
            by_art.setdefault(c.article_normalized, c)

    pricelist_items = (
        await session.scalars(
            select(Item).where(
                Item.source_id == source_id,
                Item.is_active.is_(True),
                Item.catalog_link_source.is_distinct_from("manual"),
            )
        )
    ).all()

    linked = 0
    for item in pricelist_items:
        target = _find_catalog_match(item, by_code, by_art_brand, by_art)
        if target is not None:
            item.linked_catalog_item_id = target.id
            item.catalog_link_source = "auto"
            linked += 1
        else:
            # Если раньше была auto-ссылка, а теперь каталог-карточка пропала —
            # снимаем
            if item.catalog_link_source == "auto":
                item.linked_catalog_item_id = None
                item.catalog_link_source = None
    return linked


def _find_catalog_match(
    item: Item,
    by_code: dict[str, Item],
    by_art_brand: dict[tuple[str, str], Item],
    by_art: dict[str, Item],
) -> Item | None:
    """Один lookup по приоритету: code_1c → article+brand → article."""
    if item.code_1c:
        match = by_code.get(item.code_1c.strip())
        if match is not None:
            return match
    if not item.article_normalized:
        return None
    if item.manufacturer_normalized:
        match = by_art_brand.get((item.article_normalized, item.manufacturer_normalized.lower()))
        if match is not None:
            return match
    elif item.manufacturer:
        match = by_art_brand.get((item.article_normalized, item.manufacturer.strip().lower()))
        if match is not None:
            return match
    return by_art.get(item.article_normalized)


async def apply_manufacturer_to_existing(
    session: AsyncSession, supplier_id: UUID, manufacturer: str
) -> int:
    """Принудительно проставляет manufacturer всем активным позициям прайсов
    поставщика. Используется при установке/смене Transformations.manufacturer
    через API — без этого нужно было бы пере-импортировать прайс.

    Также обновляет manufacturer_normalized для корректного матчинга.
    """
    from fasttender.models import DataSource, DataSourceType

    sources = (
        await session.scalars(
            select(DataSource.id).where(
                DataSource.supplier_id == supplier_id,
                DataSource.type == DataSourceType.SUPPLIER_PRICELIST,
            )
        )
    ).all()
    if not sources:
        return 0

    result = await session.execute(
        update(Item)
        .where(Item.source_id.in_(sources), Item.is_active.is_(True))
        .values(manufacturer=manufacturer, manufacturer_normalized=manufacturer.lower())
    )
    return result.rowcount or 0


async def backfill_supplier_skus(session: AsyncSession, supplier_id: UUID, prefix: str) -> int:
    """Присваивает supplier_sku всем активным позициям прайсов поставщика,
    у которых он ещё не задан.

    Используется при установке/смене Supplier.prefix через API — иначе
    SKU появляются только при следующем импорте, что нелогично с UX.

    Существующие непустые supplier_sku НЕ трогаем (даже если префикс сменился) —
    SKU — стабильный идентификатор, на него уже могли сослаться. Mix старых
    и новых префиксов — приемлемая цена за стабильность.
    """
    from fasttender.models import DataSource, DataSourceType

    sources = (
        await session.scalars(
            select(DataSource).where(
                DataSource.supplier_id == supplier_id,
                DataSource.type == DataSourceType.SUPPLIER_PRICELIST,
            )
        )
    ).all()

    backfilled = 0
    for source in sources:
        assigner = await build_sku_assigner(session, source.id, prefix)
        items = (
            await session.scalars(
                select(Item)
                .where(
                    Item.source_id == source.id,
                    Item.supplier_sku.is_(None),
                    Item.is_active.is_(True),
                )
                .order_by(Item.created_at, Item.article_normalized, Item.id)
            )
        ).all()
        for item in items:
            key = _item_dedupe_key(item)
            if key is not None and key in assigner.reserved:
                item.supplier_sku = assigner.reserved[key]
            else:
                item.supplier_sku = f"{prefix}-{assigner.next_num:06d}"
                assigner.next_num += 1
            backfilled += 1
    return backfilled


@dataclass
class SkuAssigner:
    """Генератор внутренних SKU позиций прайса (см. миграцию 0007).

    Стабильность: при пере-загрузке прайса позиции, которые уже были,
    сохраняют ранее присвоенный SKU. Новые получают следующий свободный
    номер вида `<prefix>-<NNNNNN>`. Счётчик берётся как `MAX(номер) + 1`
    среди всех существующих SKU в источнике (включая деактивированные —
    чтобы номер не вернулся к ранее удалённой позиции).
    """

    prefix: str
    reserved: dict[tuple[str, str], str] = field(default_factory=dict)
    next_num: int = 1

    def assign(self, parsed: ParsedItem) -> str:
        key = _dedupe_key(parsed)
        if key is not None and key in self.reserved:
            return self.reserved[key]
        sku = f"{self.prefix}-{self.next_num:06d}"
        self.next_num += 1
        return sku


async def build_sku_assigner(session: AsyncSession, source_id: UUID, prefix: str) -> SkuAssigner:
    """Создаёт SkuAssigner с зарезервированными SKU по всем существующим
    позициям источника (active и deactivated)."""
    stmt = select(Item).where(
        Item.source_id == source_id,
        Item.supplier_sku.is_not(None),
    )
    reserved: dict[tuple[str, str], str] = {}
    max_num = 0
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")

    for item in (await session.scalars(stmt)).all():
        sku = item.supplier_sku
        if sku is None:
            continue
        key = _item_dedupe_key(item)
        # Last write wins: если у двух позиций (active+deactivated) одинаковый
        # composite key, оставляем самый свежий SKU
        if key is not None and key not in reserved:
            reserved[key] = sku
        m = pattern.match(sku)
        if m:
            max_num = max(max_num, int(m.group(1)))

    return SkuAssigner(prefix=prefix, reserved=reserved, next_num=max_num + 1)


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


def prices_to_jsonb(parsed: ParsedItem) -> list[dict]:
    """Сериализация ParsedItem.prices → JSONB-массив для Item.prices.

    amount хранится строкой — JSONB не имеет Decimal, а float терял бы
    точность (цены вроде 22614.7500). При чтении парсим обратно Decimal(str).
    """
    return [
        {
            "amount": str(p.amount),
            "vat": p.vat.value,
            "tier": p.tier,
            "label": p.label,
        }
        for p in parsed.prices
    ]


def build_orm_item(source_id: UUID, parsed: ParsedItem, *, supplier_sku: str | None = None) -> Item:
    """Маппинг ParsedItem → ORM Item.

    attributes остаётся {} — характеристики в Фазе 1 не извлекаются (раздел 4.2).
    supplier_sku передаётся только при импорте прайса поставщика с заданным
    префиксом — см. SkuAssigner и build_sku_assigner.

    id присваиваем явно (а не через mapped column default=uuid4) чтобы
    он был доступен ДО flush'а — нужно для REPLACE-логики которая
    собирает touched_ids set до отправки SQL.
    """
    return Item(
        id=uuid4(),
        source_id=source_id,
        article_raw=parsed.article,
        article_normalized=normalize_article(parsed.article),
        code_1c=parsed.code_1c,
        supplier_sku=supplier_sku,
        name=parsed.name,
        name_normalized=normalize_name(parsed.name),
        manufacturer=parsed.manufacturer,
        manufacturer_normalized=(parsed.manufacturer.lower() if parsed.manufacturer else None),
        category_path=parsed.category,
        price=parsed.price,
        currency=parsed.currency,
        prices=prices_to_jsonb(parsed),
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
    *,
    sku_assigner: SkuAssigner | None = None,
    include_inactive: bool = False,
) -> tuple[int, int, set[UUID]]:
    """MERGE/REPLACE: composite lookup. Существующие обновляются, новые INSERT.

    Lookup keys (приоритет такой же как в _dedupe_key):
      1. code_1c (когда есть) — primary identity 1С
      2. (article_normalized, manufacturer_normalized) — для не-1С источников
      3. article_normalized — fallback когда нет бренда

    include_inactive: если True, ищем существующие позиции среди
    deactivated тоже — нужно для REPLACE-режима чтобы re-активировать
    «потерянные» позиции вместо создания дублей.

    Возвращает (imported, updated, touched_ids) — IDs всех позиций
    которые мы либо обновили, либо вставили (need для REPLACE-deactivate).
    """
    codes = [i.code_1c.strip() for i in items if i.code_1c]
    articles = [a for a in (normalize_article(i.article) for i in items) if a is not None]

    existing_by_code: dict[str, Item] = {}
    existing_by_art_brand: dict[tuple[str, str | None], Item] = {}

    # Lookup существующих позиций. Для MERGE — только active, для REPLACE —
    # и inactive тоже (re-активируем «вернувшуюся» позицию вместо создания
    # дубля). Грузим всё что может пересечься, потом маппим в Python.
    base_filter = [Item.source_id == source_id]
    if not include_inactive:
        base_filter.append(Item.is_active.is_(True))

    # Батчим IN-списки: на больших каталогах единый IN превышал лимит
    # bind-параметров asyncpg (см. _PARAM_CHUNK).
    for code_batch in _chunked(codes, _PARAM_CHUNK):
        stmt = select(Item).where(*base_filter, Item.code_1c.in_(code_batch))
        for row in (await session.scalars(stmt)).all():
            if row.code_1c:
                # active имеет приоритет над inactive при коллизии
                if row.code_1c not in existing_by_code or row.is_active:
                    existing_by_code[row.code_1c] = row

    for article_batch in _chunked(articles, _PARAM_CHUNK):
        stmt = select(Item).where(
            *base_filter,
            Item.article_normalized.in_(article_batch),
            Item.code_1c.is_(None),
        )
        for row in (await session.scalars(stmt)).all():
            if row.article_normalized:
                brand = (
                    row.manufacturer_normalized.strip().lower()
                    if row.manufacturer_normalized
                    else None
                )
                key = (row.article_normalized, brand)
                if key not in existing_by_art_brand or row.is_active:
                    existing_by_art_brand[key] = row

    imported = 0
    updated = 0
    touched_ids: set[UUID] = set()
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
            target.prices = prices_to_jsonb(item)
            target.unit = item.unit
            target.is_active = True  # re-активация если была deactivated
            # Backfill SKU для позиций, импортированных до появления feature
            if sku_assigner is not None and not target.supplier_sku:
                target.supplier_sku = sku_assigner.assign(item)
            touched_ids.add(target.id)
            updated += 1
        else:
            sku = sku_assigner.assign(item) if sku_assigner is not None else None
            new_item = build_orm_item(source_id, item, supplier_sku=sku)
            session.add(new_item)
            touched_ids.add(new_item.id)  # id генерится python-side (uuid4)
            imported += 1
    return imported, updated, touched_ids


async def apply_to_source(
    session: AsyncSession,
    source: DataSource,
    parsed_items: list[ParsedItem],
    mode: ImportMode,
    report: ImportReport,
    *,
    supplier_prefix: str | None = None,
) -> None:
    """Применяет уже валидированные ParsedItem к источнику в выбранном режиме.

    Заполняет соответствующие поля report (rows_imported / rows_updated /
    rows_deactivated). Не выполняет commit — это ответственность вызывающего.

    supplier_prefix: если задан, каждой позиции присваивается внутренний SKU
    `<prefix>-<NNNNNN>`. Стабильно при пере-загрузке (см. SkuAssigner).
    Передаётся только из PriceListImporter; для каталога компании None.
    """
    sku_assigner = (
        await build_sku_assigner(session, source.id, supplier_prefix) if supplier_prefix else None
    )

    if mode is ImportMode.REPLACE:
        # REPLACE через upsert: находим существующие (включая deactivated)
        # по composite-ключу — обновляем in-place, сохраняем ID. Это критично
        # потому что на Item ссылаются match_candidate и verification — при
        # старом подходе (deactivate-all + insert-new) исторические ссылки
        # указывали на «битые» deactivated-записи, хотя физически товар жив.
        # В конце deactivate всё что не попало в новый файл.
        imported, updated, touched_ids = await upsert_items(
            session,
            source.id,
            parsed_items,
            sku_assigner=sku_assigner,
            include_inactive=True,
        )
        # flush чтобы INSERT'ы новых items дошли до БД до вычисления разницы
        await session.flush()
        # Деактивируем всё, что не попало в новый файл. Раньше тут был
        # `id NOT IN (touched_ids)`, но на больших каталогах (>32767 строк)
        # список bind-параметров превышал лимит asyncpg (инцидент 2026-06-05).
        # Считаем разницу в Python и гасим батчами IN: active_ids после upsert
        # = (нетронутые active) ∪ (обновлённые) ∪ (новые); вычитая touched_ids
        # получаем ровно нетронутые active = то, что исчезло из файла.
        active_ids = set(
            (
                await session.scalars(
                    select(Item.id).where(
                        Item.source_id == source.id, Item.is_active.is_(True)
                    )
                )
            ).all()
        )
        to_deactivate = list(active_ids - touched_ids)
        deactivated = 0
        for id_batch in _chunked(to_deactivate, _PARAM_CHUNK):
            result = await session.execute(
                update(Item)
                .where(Item.id.in_(id_batch))
                .values(is_active=False)
                .execution_options(synchronize_session=False)
            )
            deactivated += result.rowcount or 0
        report.rows_imported = imported
        report.rows_updated = updated
        report.rows_deactivated = deactivated
    elif mode is ImportMode.MERGE:
        imported, updated, _touched = await upsert_items(
            session, source.id, parsed_items, sku_assigner=sku_assigner
        )
        report.rows_imported = imported
        report.rows_updated = updated
    else:  # pragma: no cover — защита от расширения enum'а
        from fasttender.services.importer.types import ImportError

        raise ImportError(f"Неизвестный режим импорта: {mode}")

    source.last_synced_at = now_utc()

    # После вставки/обновления — auto-link к каталогу (только для прайсов
    # поставщиков; каталог сам с собой не связываем)
    from fasttender.models import DataSourceType

    if source.type is DataSourceType.SUPPLIER_PRICELIST:
        # flush чтобы новые позиции были видны в SELECT внутри auto_link
        await session.flush()
        await auto_link_to_catalog(session, source.id)
