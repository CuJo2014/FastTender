"""Интеграционные тесты импорта прайсов поставщиков."""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import DataSource, DataSourceType, Item, Supplier
from fasttender.models.enums import MatchType
from fasttender.models.match_candidate import MatchCandidate
from fasttender.models.spec_item import SpecItem
from fasttender.models.specification import Specification
from fasttender.services.importer import (
    CatalogImporter,
    ImportError,
    ImportMode,
    PriceListImporter,
)
from fasttender.services.importer.pricelist import CONFIG_KEY_MAPPING
from fasttender.services.parser import ColumnMapping, SpecField
from tests.fixtures.spec_builders import make_xlsx


@pytest.fixture
def importer() -> PriceListImporter:
    return PriceListImporter()


@pytest.fixture
def catalog_importer() -> CatalogImporter:
    return CatalogImporter()


async def _make_supplier(session: AsyncSession, name: str) -> Supplier:
    supplier = Supplier(name=name, contact_email=None, meta={})
    session.add(supplier)
    await session.flush()
    return supplier


async def test_first_import_creates_pricelist_source_and_learns_mapping(
    session: AsyncSession,
    importer: PriceListImporter,
    tmp_path: Path,
) -> None:
    """Первый импорт лениво создаёт DataSource и сохраняет автодетектированный mapping."""
    supplier = await _make_supplier(session, "ООО Поставщик-1")

    path = make_xlsx(
        tmp_path / "pl_v1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["S1-001", "Болт от поставщика 1", "10.50"],
            ["S1-002", "Гайка от поставщика 1", "3.20"],
        ],
    )

    report = await importer.import_file(
        session, supplier_id=supplier.id, path=path, mode=ImportMode.REPLACE
    )
    await session.commit()

    assert report.rows_imported == 2

    # Создан DataSource нужного типа, привязан к поставщику
    source = await session.scalar(select(DataSource).where(DataSource.supplier_id == supplier.id))
    assert source is not None
    assert source.type is DataSourceType.SUPPLIER_PRICELIST
    assert source.name == "Прайс: ООО Поставщик-1"

    # Mapping сохранился в config — система «выучила» структуру
    saved = source.config.get(CONFIG_KEY_MAPPING)
    assert saved is not None
    assert saved["article"] == 0
    assert saved["name"] == 1
    assert saved["price"] == 2


async def test_second_import_reuses_saved_mapping(
    session: AsyncSession,
    importer: PriceListImporter,
    tmp_path: Path,
) -> None:
    """Второй импорт того же поставщика применяет сохранённый шаблон."""
    supplier = await _make_supplier(session, "ООО Поставщик-1")

    # Первый файл с нормальной шапкой
    first = make_xlsx(
        tmp_path / "v1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-001", "Позиция A", "100"],
        ],
    )
    await importer.import_file(
        session, supplier_id=supplier.id, path=first, mode=ImportMode.REPLACE
    )
    await session.commit()

    # Второй файл — НЕстандартная шапка (без узнаваемых заголовков),
    # но т.к. mapping уже выучен, импорт пройдёт по сохранённой схеме.
    second = make_xlsx(
        tmp_path / "v2.xlsx",
        rows=[
            ["xxx", "yyy", "zzz"],  # бесполезные заголовки
            ["A-002", "Позиция B", "200"],
        ],
    )
    report = await importer.import_file(
        session, supplier_id=supplier.id, path=second, mode=ImportMode.MERGE
    )
    await session.commit()

    assert report.rows_imported == 1  # A-002 — новый
    # «xxx/yyy/zzz» интерпретировалось как шапка, т.к. mapping override применился
    items = (await session.scalars(select(Item))).all()
    by_article = {i.article_normalized: i for i in items}
    assert by_article["A002"].name == "Позиция B"


async def test_explicit_mapping_override_wins(
    session: AsyncSession,
    importer: PriceListImporter,
    tmp_path: Path,
) -> None:
    """Если передан mapping_override, он применяется даже при наличии сохранённого."""
    supplier = await _make_supplier(session, "ООО Поставщик-1")

    path = make_xlsx(
        tmp_path / "weird.xlsx",
        rows=[
            ["a", "b", "c", "d"],
            ["IGNORE-1", "Кривая позиция", 999, 999],
            ["GOOD-1", "Правильная позиция", 50, "ШТ"],
        ],
    )
    mapping = ColumnMapping(
        columns={
            SpecField.ARTICLE: 0,
            SpecField.NAME: 1,
            SpecField.PRICE: 2,
            SpecField.UNIT: 3,
        }
    )
    report = await importer.import_file(
        session,
        supplier_id=supplier.id,
        path=path,
        mode=ImportMode.REPLACE,
        mapping_override=mapping,
    )
    await session.commit()

    # Mapping override: первая «шапка» становится строкой данных, поэтому
    # обе строки берутся как items (включая IGNORE-1)
    assert report.rows_imported == 2
    items = (await session.scalars(select(Item))).all()
    by_article = {i.article_normalized: i for i in items}
    assert by_article["GOOD1"].price == Decimal("50")
    assert by_article["GOOD1"].unit == "ШТ"


async def test_pricelist_for_unknown_supplier_raises(
    session: AsyncSession,
    importer: PriceListImporter,
    tmp_path: Path,
) -> None:
    path = make_xlsx(
        tmp_path / "v.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["X-1", "X", "1"],
        ],
    )
    with pytest.raises(ImportError, match="не найден"):
        await importer.import_file(session, supplier_id=uuid4(), path=path, mode=ImportMode.REPLACE)


async def test_different_suppliers_get_independent_sources(
    session: AsyncSession,
    importer: PriceListImporter,
    tmp_path: Path,
) -> None:
    """Импорт от разных поставщиков → разные DataSource, изоляция данных."""
    s1 = await _make_supplier(session, "Supplier-1")
    s2 = await _make_supplier(session, "Supplier-2")

    file_s1 = make_xlsx(
        tmp_path / "s1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["COMMON-001", "Болт от S1", "10"],
        ],
    )
    file_s2 = make_xlsx(
        tmp_path / "s2.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["COMMON-001", "Болт от S2 (другая цена)", "12"],
        ],
    )

    await importer.import_file(session, supplier_id=s1.id, path=file_s1, mode=ImportMode.REPLACE)
    await importer.import_file(session, supplier_id=s2.id, path=file_s2, mode=ImportMode.REPLACE)
    await session.commit()

    # Один и тот же артикул в двух разных source — это норма (раздел 8.2)
    items = (await session.scalars(select(Item).order_by(Item.price))).all()
    assert len(items) == 2
    assert items[0].price == Decimal("10")
    assert items[1].price == Decimal("12")
    assert items[0].source_id != items[1].source_id


async def test_catalog_and_pricelist_coexist_with_same_article(
    session: AsyncSession,
    catalog_importer: CatalogImporter,
    importer: PriceListImporter,
    tmp_path: Path,
) -> None:
    """Один артикул может быть и в каталоге компании, и в прайсе — это разные source.

    Это ключевой инвариант раздела 8.2: единая таблица ITEM, разные источники.
    Unique-индекс (source_id, article_normalized) не должен мешать.
    """
    supplier = await _make_supplier(session, "Конкурирующий поставщик")

    cat_file = make_xlsx(
        tmp_path / "cat.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["SHARED-001", "Наша позиция (каталог)", "100"],
        ],
    )
    pl_file = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["SHARED-001", "Их позиция (прайс)", "80"],
        ],
    )

    await catalog_importer.import_file(session, cat_file, mode=ImportMode.REPLACE)
    await importer.import_file(
        session, supplier_id=supplier.id, path=pl_file, mode=ImportMode.REPLACE
    )
    await session.commit()

    items = (await session.scalars(select(Item).order_by(Item.price))).all()
    assert len(items) == 2
    assert [i.article_normalized for i in items] == ["SHARED001", "SHARED001"]
    # Дифференциация — через source.type
    sources_by_item = {i.id: (await session.get(DataSource, i.source_id)).type for i in items}
    types = list(sources_by_item.values())
    assert DataSourceType.COMPANY_CATALOG in types
    assert DataSourceType.SUPPLIER_PRICELIST in types


async def test_pricelist_applies_supplier_transformations(
    session: AsyncSession,
    importer: PriceListImporter,
    tmp_path: Path,
) -> None:
    """Конфиг трансформаций в supplier.meta применяется при импорте."""
    supplier = Supplier(
        name="Мир Инструмента",
        contact_email=None,
        meta={
            "transformations": {
                "brand_regex": r"^(.+?)\s*//\s*(.+?)\s*$",
                "vat_included": True,
                "vat_rate": 20,
                "default_unit": "шт",
                "default_currency": "RUB",
            }
        },
    )
    session.add(supplier)
    await session.flush()

    path = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Молоток 200г // Sparta", "120"],
            ["A-2", "Гайка М10", "60"],  # без бренда — не парсится
        ],
    )
    await importer.import_file(session, supplier_id=supplier.id, path=path, mode=ImportMode.REPLACE)
    await session.commit()

    items = {i.article_normalized: i for i in (await session.scalars(select(Item))).all()}
    # brand_regex сработал
    assert items["A1"].name == "Молоток 200г"
    assert items["A1"].manufacturer == "Sparta"
    # НДС убран (120 / 1.2 = 100)
    assert items["A1"].price == Decimal("100.0000")
    # Дефолты подставлены
    assert items["A1"].unit == "шт"
    assert items["A1"].currency == "RUB"
    # На строке без бренда — name неизменён, но дефолты применились
    assert items["A2"].manufacturer is None
    assert items["A2"].name == "Гайка М10"
    assert items["A2"].price == Decimal("50.0000")  # 60 / 1.2


async def test_merge_mode_updates_existing_pricelist_items(
    session: AsyncSession,
    importer: PriceListImporter,
    tmp_path: Path,
) -> None:
    supplier = await _make_supplier(session, "Supplier-1")

    first = make_xlsx(
        tmp_path / "v1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Старая цена", "100"],
        ],
    )
    second = make_xlsx(
        tmp_path / "v2.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Новая цена", "150"],
            ["A-2", "Новая позиция", "200"],
        ],
    )

    await importer.import_file(
        session, supplier_id=supplier.id, path=first, mode=ImportMode.REPLACE
    )
    await session.commit()

    report = await importer.import_file(
        session, supplier_id=supplier.id, path=second, mode=ImportMode.MERGE
    )
    await session.commit()

    assert report.rows_updated == 1
    assert report.rows_imported == 1

    items = (await session.scalars(select(Item))).all()
    by_article = {i.article_normalized: i for i in items}
    assert by_article["A1"].price == Decimal("150")
    assert by_article["A1"].name == "Новая цена"


async def test_replace_reimport_keeps_match_candidate_valid(
    session: AsyncSession,
    importer: PriceListImporter,
    tmp_path: Path,
) -> None:
    """Регрессия инцидента 2026-06-02 (фидбэк MIK): REPLACE-ре-импорт прайса
    не плодит deactivated-дубли, а match_candidate.item_id остаётся на том же
    физически живом (active) item. До рефакторинга REPLACE деактивировал все
    старые позиции и вставлял новые с новыми UUID — исторические ссылки из
    match_candidate указывали на «битые» deactivated-записи навсегда.
    """
    supplier = Supplier(name="МИК", prefix="MIK", contact_email=None, meta={})
    session.add(supplier)
    await session.flush()

    pl = make_xlsx(
        tmp_path / "mik.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Кабель ВВГ 3х2.5", "100"],
            ["A-2", "Кабель ВВГ 3х1.5", "80"],
        ],
    )
    await importer.import_file(session, supplier_id=supplier.id, path=pl, mode=ImportMode.REPLACE)
    await session.commit()

    item = await session.scalar(select(Item).where(Item.article_normalized == "A1"))
    original_item_id = item.id
    original_sku = item.supplier_sku

    # Менеджер сматчил спеку на эту прайс-позицию
    spec = Specification(source_filename="spec.xlsx", storage_path="/tmp/spec.xlsx")
    session.add(spec)
    await session.flush()
    spec_item = SpecItem(spec_id=spec.id, line_number=1, name_raw="кабель ввг 3*2.5")
    session.add(spec_item)
    await session.flush()
    mc = MatchCandidate(
        spec_item_id=spec_item.id,
        item_id=item.id,
        confidence=0.95,
        match_type=MatchType.EXACT_ARTICLE,
        rank=1,
    )
    session.add(mc)
    await session.commit()
    mc_id = mc.id

    # Ре-импорт того же прайса (REPLACE)
    await importer.import_file(session, supplier_id=supplier.id, path=pl, mode=ImportMode.REPLACE)
    await session.commit()

    # 1. Никаких дублей: ровно 2 позиции, обе active
    total = await session.scalar(select(func.count()).select_from(Item))
    active = await session.scalar(select(func.count()).select_from(Item).where(Item.is_active))
    assert total == 2, f"ожидалось 2 позиции, накопились дубли: {total}"
    assert active == 2

    # 2. match_candidate.item_id указывает на тот же живой item
    mc_after = await session.get(MatchCandidate, mc_id)
    assert mc_after is not None
    assert mc_after.item_id == original_item_id, "FK уехал на новый UUID"
    linked = await session.get(Item, mc_after.item_id)
    assert linked.is_active, "match указывает на deactivated-копию (исходный баг)"

    # 3. supplier_sku стабилен
    assert linked.supplier_sku == original_sku
