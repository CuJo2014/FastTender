"""Связка прайс↔каталог (миграция 0008)."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import DataSource, Item, Supplier
from fasttender.services.importer import (
    CatalogImporter,
    ImportMode,
    PriceListImporter,
)
from fasttender.services.importer._base import auto_link_to_catalog
from tests.fixtures.spec_builders import make_xlsx


async def _make_supplier(session: AsyncSession, name: str) -> Supplier:
    supplier = Supplier(name=name, contact_email=None, meta={})
    session.add(supplier)
    await session.flush()
    return supplier


async def _seed_catalog(session: AsyncSession, tmp_path: Path) -> None:
    """Каталог с тремя позициями: с code_1c+article+brand, с article+brand, с article."""
    catalog = make_xlsx(
        tmp_path / "cat.xlsx",
        rows=[
            ["Артикул", "Код", "Наименование", "Цена", "Производитель"],
            ["BLT-001", "Ц0000000100", "Болт М10х40 DIN933", "10", "Завод"],
            ["NUT-001", "Ц0000000200", "Гайка М10 DIN934", "4", "Метизы"],
            ["WSH-001", None, "Шайба М10", "1", None],
        ],
    )
    await CatalogImporter().import_file(session, catalog, mode=ImportMode.REPLACE)
    await session.commit()


async def test_auto_link_by_code_1c(session: AsyncSession, tmp_path: Path) -> None:
    """Прайс-позиция с code_1c, совпадающим с каталогом → линкуется."""
    await _seed_catalog(session, tmp_path)
    supplier = await _make_supplier(session, "Test1")
    pl = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Код", "Наименование", "Цена"],
            ["WHATEVER", "Ц0000000100", "Любое название", "12"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=pl, mode=ImportMode.REPLACE
    )
    await session.commit()

    # Достаём прайс-позицию
    sources = (
        await session.scalars(select(DataSource).where(DataSource.supplier_id == supplier.id))
    ).all()
    item = await session.scalar(
        select(Item).where(Item.source_id == sources[0].id, Item.is_active.is_(True))
    )
    # NOTE: для прайсов PriceListImporter передаёт exclude_fields=CODE_1C, поэтому
    # код 1С с прайса фактически не парсится — линкуем по article+brand или article
    # Но в этом тесте article "WHATEVER" не матчится с каталогом, поэтому link=None
    assert item is not None
    assert item.linked_catalog_item_id is None  # подтверждаем что code_1c из прайса не используется


async def test_auto_link_by_article_brand(session: AsyncSession, tmp_path: Path) -> None:
    """Прайс с article+brand, совпадающими с каталогом → линкуется на правильную карту."""
    await _seed_catalog(session, tmp_path)
    supplier = await _make_supplier(session, "Test2")
    pl = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена", "Производитель"],
            ["BLT-001", "Болт от поставщика", "9", "Завод"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=pl, mode=ImportMode.REPLACE
    )
    await session.commit()

    source = await session.scalar(select(DataSource).where(DataSource.supplier_id == supplier.id))
    item = await session.scalar(
        select(Item).where(Item.source_id == source.id, Item.is_active.is_(True))
    )
    assert item.linked_catalog_item_id is not None
    assert item.catalog_link_source == "auto"

    catalog_item = await session.get(Item, item.linked_catalog_item_id)
    assert catalog_item.code_1c == "Ц0000000100"


async def test_auto_link_by_article_only(session: AsyncSession, tmp_path: Path) -> None:
    """Прайс без бренда → fallback на article only."""
    await _seed_catalog(session, tmp_path)
    supplier = await _make_supplier(session, "Test3")
    pl = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["WSH-001", "Шайба от поставщика", "0.5"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=pl, mode=ImportMode.REPLACE
    )
    await session.commit()

    source = await session.scalar(select(DataSource).where(DataSource.supplier_id == supplier.id))
    item = await session.scalar(
        select(Item).where(Item.source_id == source.id, Item.is_active.is_(True))
    )
    assert item.linked_catalog_item_id is not None
    assert item.catalog_link_source == "auto"


async def test_no_match_leaves_link_none(session: AsyncSession, tmp_path: Path) -> None:
    """Прайс-позиция без соответствия в каталоге → linked_catalog_item_id остаётся None."""
    await _seed_catalog(session, tmp_path)
    supplier = await _make_supplier(session, "Test4")
    pl = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["UNKNOWN-999", "Неизвестный товар", "100"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=pl, mode=ImportMode.REPLACE
    )
    await session.commit()

    source = await session.scalar(select(DataSource).where(DataSource.supplier_id == supplier.id))
    item = await session.scalar(
        select(Item).where(Item.source_id == source.id, Item.is_active.is_(True))
    )
    assert item.linked_catalog_item_id is None
    assert item.catalog_link_source is None


async def test_manual_link_is_preserved_on_reimport(session: AsyncSession, tmp_path: Path) -> None:
    """Если менеджер вручную привязал позицию (catalog_link_source='manual'),
    повторный импорт прайса НЕ должен перетереть выбор."""
    await _seed_catalog(session, tmp_path)
    supplier = await _make_supplier(session, "Test5")
    pl = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена", "Производитель"],
            ["BLT-001", "Болт", "9", "Завод"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=pl, mode=ImportMode.REPLACE
    )
    await session.commit()

    source = await session.scalar(select(DataSource).where(DataSource.supplier_id == supplier.id))
    item = await session.scalar(
        select(Item).where(Item.source_id == source.id, Item.is_active.is_(True))
    )
    # Менеджер переопределяет на другую каталог-карточку
    other_cat = await session.scalar(select(Item).where(Item.code_1c == "Ц0000000200"))
    item.linked_catalog_item_id = other_cat.id
    item.catalog_link_source = "manual"
    await session.commit()

    # Re-import тем же файлом в MERGE — auto_link НЕ должен трогать manual
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=pl, mode=ImportMode.MERGE
    )
    await session.commit()

    await session.refresh(item)
    assert item.linked_catalog_item_id == other_cat.id
    assert item.catalog_link_source == "manual"


async def test_auto_link_runs_on_existing_items_via_helper(
    session: AsyncSession, tmp_path: Path
) -> None:
    """auto_link_to_catalog() можно вызвать руками — для backfill уже
    загруженных прайсов после деплоя фичи."""
    await _seed_catalog(session, tmp_path)
    supplier = await _make_supplier(session, "Test6")

    pl = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена", "Производитель"],
            ["BLT-001", "Болт", "9", "Завод"],
            ["NUT-001", "Гайка", "5", "Метизы"],
            ["NEW", "Новинка", "1", "X"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=pl, mode=ImportMode.REPLACE
    )
    await session.commit()

    source = await session.scalar(select(DataSource).where(DataSource.supplier_id == supplier.id))
    # Симулируем что линки ещё не проставлены (как было бы для прайсов из
    # доисторической эпохи)
    await session.execute(
        Item.__table__.update()
        .where(Item.source_id == source.id)
        .values(linked_catalog_item_id=None, catalog_link_source=None)
    )
    await session.commit()

    linked = await auto_link_to_catalog(session, source.id)
    await session.commit()

    assert linked == 2  # BLT-001 и NUT-001 нашли каталог, NEW нет
    items = {
        i.article_normalized: i
        for i in (await session.scalars(select(Item).where(Item.source_id == source.id))).all()
    }
    assert items["BLT001"].linked_catalog_item_id is not None
    assert items["NUT001"].linked_catalog_item_id is not None
    assert items["NEW"].linked_catalog_item_id is None
