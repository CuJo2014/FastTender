"""Внутренний SKU позиций прайса (миграция 0007).

См. обсуждение 2026-05-30: у позиций прайса поставщика не было
стабильного идентификатора (Артикул может меняться при обновлении).
supplier_sku — это `<prefix>-<NNNNNN>`, где prefix — 3 символа поставщика.
"""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import Item, Supplier
from fasttender.services.importer import (
    CatalogImporter,
    ImportMode,
    PriceListImporter,
)
from tests.fixtures.spec_builders import make_xlsx


async def _make_supplier(session: AsyncSession, name: str, prefix: str | None) -> Supplier:
    supplier = Supplier(name=name, prefix=prefix, contact_email=None, meta={})
    session.add(supplier)
    await session.flush()
    return supplier


async def test_pricelist_assigns_supplier_sku_when_prefix_set(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    supplier = await _make_supplier(session, "Сибинструмент", "SIB")
    path = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["X-1", "Болт", "10"],
            ["X-2", "Гайка", "5"],
            ["X-3", "Шайба", "1"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=path, mode=ImportMode.REPLACE
    )
    await session.commit()

    items = (await session.scalars(select(Item).order_by(Item.supplier_sku))).all()
    skus = [i.supplier_sku for i in items]
    assert skus == ["SIB-000001", "SIB-000002", "SIB-000003"]


async def test_pricelist_without_prefix_skips_sku(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    supplier = await _make_supplier(session, "Без префикса", None)
    path = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Что-то", "1"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=path, mode=ImportMode.REPLACE
    )
    await session.commit()

    items = (await session.scalars(select(Item))).all()
    assert all(i.supplier_sku is None for i in items)


async def test_sku_stable_across_replace_reimport(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """REPLACE второй раз: совпадающие позиции сохраняют свой SKU,
    новые получают следующий номер. Это главный value-proposition фичи.
    """
    supplier = await _make_supplier(session, "Сибинструмент", "SIB")

    first = make_xlsx(
        tmp_path / "v1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Болт", "10"],
            ["A-2", "Гайка", "5"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=first, mode=ImportMode.REPLACE
    )
    await session.commit()

    sku_before = {
        i.article_normalized: i.supplier_sku
        for i in (await session.scalars(select(Item).where(Item.is_active))).all()
    }
    assert sku_before == {"A1": "SIB-000001", "A2": "SIB-000002"}

    # Второй REPLACE — A-1 остаётся, A-2 нет (исчезла), A-3 новая
    second = make_xlsx(
        tmp_path / "v2.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Болт обновлённый", "12"],
            ["A-3", "Шайба", "1"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=second, mode=ImportMode.REPLACE
    )
    await session.commit()

    active = {
        i.article_normalized: i.supplier_sku
        for i in (await session.scalars(select(Item).where(Item.is_active))).all()
    }
    # A-1 сохранил свой SKU несмотря на пере-загрузку
    assert active["A1"] == "SIB-000001"
    # A-3 новый → следующий номер. A-2 был SIB-000002 (deactivated),
    # счётчик не возвращается к нему — A-3 получает 000003
    assert active["A3"] == "SIB-000003"


async def test_sku_stable_across_merge_reimport(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    supplier = await _make_supplier(session, "Сибинструмент", "SIB")

    first = make_xlsx(
        tmp_path / "v1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Болт", "10"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=first, mode=ImportMode.REPLACE
    )
    await session.commit()

    # MERGE: добавляем новую позицию, обновляем существующую
    second = make_xlsx(
        tmp_path / "v2.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Болт обновлённый", "12"],
            ["A-2", "Гайка", "5"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=second, mode=ImportMode.MERGE
    )
    await session.commit()

    items = {i.article_normalized: i for i in (await session.scalars(select(Item))).all()}
    assert items["A1"].supplier_sku == "SIB-000001"
    assert items["A1"].name == "Болт обновлённый"
    assert items["A2"].supplier_sku == "SIB-000002"


async def test_catalog_import_does_not_assign_sku(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Каталог компании никогда не получает supplier_sku — там есть code_1c."""
    path = make_xlsx(
        tmp_path / "cat.xlsx",
        rows=[
            ["Артикул", "Код", "Наименование", "Цена"],
            ["A-1", "Ц0000000100", "Позиция", "10"],
        ],
    )
    await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    items = (await session.scalars(select(Item))).all()
    assert all(i.supplier_sku is None for i in items)


async def test_two_suppliers_with_same_prefix_rejected_by_db(
    session: AsyncSession,
) -> None:
    """ux_supplier_prefix — partial unique. Два поставщика с одним prefix
    нельзя сохранить.
    """
    await _make_supplier(session, "Первый", "ABC")
    await session.commit()

    # flush() в _make_supplier поднимет IntegrityError на втором с тем же prefix
    with pytest.raises(IntegrityError, match="ux_supplier_prefix"):
        await _make_supplier(session, "Второй", "ABC")


async def test_merge_backfills_sku_when_prefix_added_later(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Кейс: поставщик создан без prefix, прайс залит, потом prefix добавили.
    Следующий MERGE должен присвоить SKU существующим позициям.
    """
    supplier = await _make_supplier(session, "Поставщик", None)
    path = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Болт", "10"],
            ["A-2", "Гайка", "5"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=path, mode=ImportMode.REPLACE
    )
    await session.commit()

    # Префикс добавили задним числом
    supplier.prefix = "POS"
    await session.commit()

    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=path, mode=ImportMode.MERGE
    )
    await session.commit()

    items = {
        i.article_normalized: i.supplier_sku for i in (await session.scalars(select(Item))).all()
    }
    assert items["A1"] == "POS-000001"
    assert items["A2"] == "POS-000002"
