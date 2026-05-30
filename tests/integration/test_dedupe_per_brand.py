"""Регрессионные тесты дедупликации по composite-ключу.

Инцидент 2026-05-30: реальный каталог 96K имел 1245 «дубликатов»
артикулов которые на самом деле были разными товарами разных
производителей с одинаковыми артикулами (типичная ситуация для
стандартных метизов и пр.). Старый unique-индекс (миграция 0004) их
блокировал. Миграция 0006 переделала уникальность на composite.

Эти тесты фиксируют новое поведение:
  - one article + different brands → оба сохраняются
  - one article + same brand       → второй дедуплицируется
  - code_1c всегда override        → дедуп по нему
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import Item
from fasttender.services.importer import CatalogImporter, ImportMode
from tests.fixtures.spec_builders import make_xlsx


async def test_same_article_different_brands_both_kept(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Один и тот же артикул у двух разных брендов — оба сохраняются."""
    path = make_xlsx(
        tmp_path / "cat.xlsx",
        rows=[
            ["Артикул", "Производитель", "Наименование", "Цена"],
            ["1820067700", "BOSCH", "Сверло Bosch", "100"],
            ["1820067700", "MAKITA", "Сверло Makita (тот же артикул!)", "120"],
        ],
    )
    report = await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    assert report.rows_imported == 2  # оба прошли
    assert report.rows_skipped == 0
    assert len(report.duplicates) == 0

    items = (await session.scalars(select(Item).order_by(Item.manufacturer))).all()
    assert len(items) == 2
    brands = {i.manufacturer for i in items}
    assert brands == {"BOSCH", "MAKITA"}


async def test_same_article_same_brand_deduplicates(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Артикул + бренд совпадают → реальный дубликат, второй пропускается."""
    path = make_xlsx(
        tmp_path / "cat.xlsx",
        rows=[
            ["Артикул", "Производитель", "Наименование", "Цена"],
            ["BLT-001", "KOELNER", "Болт первая версия", "10"],
            ["BLT-001", "KOELNER", "Болт вторая (дубль)", "12"],
        ],
    )
    report = await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    assert report.rows_imported == 1
    assert report.rows_skipped == 1
    assert len(report.duplicates) == 1
    dup = report.duplicates[0]
    # Ключ дедупа включает бренд → article «BLT001 [koelner]» в репорте
    assert "BLT001" in dup.article
    assert "koelner" in dup.article

    items = (await session.scalars(select(Item))).all()
    assert len(items) == 1
    assert items[0].name == "Болт первая версия"


async def test_code_1c_overrides_dedupe(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Когда есть code_1c — дедуп по нему, артикул может дублироваться свободно."""
    path = make_xlsx(
        tmp_path / "cat.xlsx",
        rows=[
            ["Артикул", "Код", "Производитель", "Наименование", "Цена"],
            ["A-1", "Ц0000000001", "BOSCH", "Первая", "10"],
            ["A-1", "Ц0000000002", "BOSCH", "Вторая (тот же арт+бренд, но другой код)", "12"],
            ["A-1", "Ц0000000001", "BOSCH", "Третья (тот же код = дубль)", "15"],
        ],
    )
    report = await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    # Первая и вторая — разные code_1c → обе сохраняются
    # Третья — code_1c как у первой → дубль
    assert report.rows_imported == 2
    assert report.rows_skipped == 1
    assert len(report.duplicates) == 1
    assert "Ц0000000001" in report.duplicates[0].article


async def test_no_article_no_code_keeps_all(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Строки без артикула и без кода — каждая уникальна, дедуп не делается."""
    path = make_xlsx(
        tmp_path / "cat.xlsx",
        rows=[
            ["Артикул", "Производитель", "Наименование", "Цена"],
            [None, "BOSCH", "Безымянный товар 1", "10"],
            [None, "BOSCH", "Безымянный товар 2 (другой!)", "12"],
        ],
    )
    report = await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()
    assert report.rows_imported == 2
    assert report.rows_skipped == 0


async def test_db_unique_constraint_blocks_real_duplicates(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Защита БД: даже если importer пропустит, partial unique индекс сработает."""
    # Без бренда, чтобы попасть в индекс с COALESCE(lower(manufacturer), '')
    path = make_xlsx(
        tmp_path / "cat.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["UNIQ-1", "Первый товар", "10"],
        ],
    )
    await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    # Повторный REPLACE с тем же артикулом + без бренда — не должен ломаться
    # (миграция 0006 + бывшая 0004: индекс учитывает is_active)
    await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    actives = (await session.scalars(select(Item).where(Item.is_active))).all()
    assert len(actives) == 1
    assert actives[0].article_raw == "UNIQ-1"
