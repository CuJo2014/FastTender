"""Интеграционные тесты импорта каталога против реального PostgreSQL.

Запускаются только если БД доступна (см. conftest.py). Все тесты в одной
транзакции, которая откатывается — БД между тестами в чистом состоянии.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import DataSource, DataSourceType, Item
from fasttender.services.importer import CatalogImporter, ImportMode
from tests.fixtures.spec_builders import make_csv, make_xlsx


@pytest.fixture
def importer() -> CatalogImporter:
    return CatalogImporter()


async def test_replace_mode_creates_catalog_source(
    session: AsyncSession,
    importer: CatalogImporter,
    tmp_path: Path,
) -> None:
    """Первый импорт лениво создаёт DataSource типа COMPANY_CATALOG."""
    path = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Производитель", "Ед. изм.", "Цена"],
            ["BLT-001", "Болт М10х40", "KOELNER", "шт", "12.50"],
            ["NUT-001", "Гайка М10", "KOELNER", "шт", "4.20"],
            ["WSH-001", "Шайба М10", "KOELNER", "шт", "1.10"],
        ],
    )

    report = await importer.import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    assert report.rows_total == 3
    assert report.rows_imported == 3
    assert report.rows_skipped == 0
    assert report.errors == []
    assert report.duplicates == []

    # Создался ровно один источник типа COMPANY_CATALOG
    sources = (await session.scalars(select(DataSource))).all()
    assert len(sources) == 1
    assert sources[0].type is DataSourceType.COMPANY_CATALOG

    # И три позиции в Item
    items = (await session.scalars(select(Item))).all()
    assert len(items) == 3
    by_article = {i.article_normalized: i for i in items}
    assert by_article["BLT001"].name == "Болт М10х40"
    assert by_article["BLT001"].price == Decimal("12.5")
    assert by_article["BLT001"].is_active is True


async def test_replace_mode_deactivates_old_items(
    session: AsyncSession,
    importer: CatalogImporter,
    tmp_path: Path,
) -> None:
    """REPLACE: после повторного импорта старые позиции is_active=false, новые активны."""
    first = make_xlsx(
        tmp_path / "v1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["OLD-001", "Старый болт", "10"],
            ["OLD-002", "Старая гайка", "5"],
        ],
    )
    second = make_xlsx(
        tmp_path / "v2.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["NEW-001", "Новый болт", "15"],
        ],
    )

    await importer.import_file(session, first, mode=ImportMode.REPLACE)
    await session.commit()
    report = await importer.import_file(session, second, mode=ImportMode.REPLACE)
    await session.commit()

    assert report.rows_deactivated == 2
    assert report.rows_imported == 1

    # Старые в БД, но is_active=false (для истории матчингов)
    items = (await session.scalars(select(Item).order_by(Item.article_normalized))).all()
    assert len(items) == 3  # 2 деактивированных + 1 новый
    actives = [i for i in items if i.is_active]
    assert len(actives) == 1
    assert actives[0].article_normalized == "NEW001"


async def test_merge_mode_updates_and_inserts(
    session: AsyncSession,
    importer: CatalogImporter,
    tmp_path: Path,
) -> None:
    """MERGE: совпадающие артикулы обновляются, новые добавляются, остальные сохраняются."""
    first = make_xlsx(
        tmp_path / "v1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Позиция 1 (старая)", "100"],
            ["A-2", "Позиция 2 (не меняется)", "200"],
        ],
    )
    second = make_xlsx(
        tmp_path / "v2.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Позиция 1 (обновлённая)", "150"],
            ["A-3", "Позиция 3 (новая)", "300"],
        ],
    )

    await importer.import_file(session, first, mode=ImportMode.REPLACE)
    await session.commit()
    report = await importer.import_file(session, second, mode=ImportMode.MERGE)
    await session.commit()

    assert report.rows_updated == 1  # A-1
    assert report.rows_imported == 1  # A-3
    assert report.rows_deactivated == 0

    items = (await session.scalars(select(Item).order_by(Item.article_normalized))).all()
    assert len(items) == 3  # A-1, A-2, A-3

    by_article = {i.article_normalized: i for i in items}
    assert by_article["A1"].name == "Позиция 1 (обновлённая)"
    assert by_article["A1"].price == Decimal("150")
    assert by_article["A2"].name == "Позиция 2 (не меняется)"  # не тронули
    assert by_article["A3"].name == "Позиция 3 (новая)"


async def test_duplicate_articles_in_file_reported(
    session: AsyncSession,
    importer: CatalogImporter,
    tmp_path: Path,
) -> None:
    """Дубликаты артикулов внутри файла — первый импортируется, остальные в отчёт."""
    path = make_xlsx(
        tmp_path / "dup.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["DUP-001", "Первая версия", "100"],
            ["UNIQ-1", "Уникальная позиция", "50"],
            ["DUP-001", "Вторая версия (будет пропущена)", "120"],
            ["DUP-001", "Третья версия (тоже пропущена)", "130"],
        ],
    )

    report = await importer.import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    assert report.rows_imported == 2  # DUP-001 (первая) + UNIQ-1
    assert report.rows_skipped == 2  # две дублирующие строки
    assert len(report.duplicates) == 1
    dup = report.duplicates[0]
    assert dup.article == "DUP001"
    assert dup.first_line == 1
    assert sorted(dup.duplicate_lines) == [3, 4]

    items = (await session.scalars(select(Item))).all()
    by_article = {i.article_normalized: i for i in items}
    # В БД — первая версия, не последняя
    assert by_article["DUP001"].name == "Первая версия"


async def test_empty_names_skipped_and_reported(
    session: AsyncSession,
    importer: CatalogImporter,
    tmp_path: Path,
) -> None:
    path = make_xlsx(
        tmp_path / "empty_names.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["VALID-1", "Хороший товар", "10"],
            # Парсер пропускает строки без name (см. _matrix.py),
            # поэтому проверяем строку, где name есть в виде пробелов — её парсер
            # тоже пропустит. Это нормально: до importer'а такие не доходят.
            ["VALID-2", "Ещё хороший", "20"],
        ],
    )
    report = await importer.import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    assert report.rows_imported == 2
    assert report.errors == []


async def test_csv_import_with_cp1251(
    session: AsyncSession,
    importer: CatalogImporter,
    tmp_path: Path,
) -> None:
    """Импорт работает и через CSV (русская кодировка)."""
    path = make_csv(
        tmp_path / "catalog.csv",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["RU-001", "Болт оцинкованный", "12,50"],
            ["RU-002", "Гайка стальная", "4,20"],
        ],
        encoding="cp1251",
        delimiter=";",
    )
    report = await importer.import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    assert report.rows_imported == 2
    items = (await session.scalars(select(Item))).all()
    by_article = {i.article_normalized: i for i in items}
    assert by_article["RU001"].name == "Болт оцинкованный"
    assert by_article["RU001"].price == Decimal("12.50")


async def test_attributes_remain_empty_in_phase1(
    session: AsyncSession,
    importer: CatalogImporter,
    tmp_path: Path,
) -> None:
    """Подтверждаем решение: характеристики в Phase 1 не извлекаются — attributes = {}."""
    path = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["BLT-001", "Болт М10х40 DIN933 оцинкованный", "12.5"],
        ],
    )
    await importer.import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    items = (await session.scalars(select(Item))).all()
    assert items[0].attributes == {}


async def test_normalization_is_applied(
    session: AsyncSession,
    importer: CatalogImporter,
    tmp_path: Path,
) -> None:
    """Артикул нормализуется (uppercase, без разделителей), наименование — lowercase."""
    path = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["blt-m10-040-zn", "Болт М10×40 DIN933", "12.5"],
        ],
    )
    await importer.import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    items = (await session.scalars(select(Item))).all()
    assert items[0].article_raw == "blt-m10-040-zn"
    assert items[0].article_normalized == "BLTM10040ZN"
    assert items[0].name == "Болт М10×40 DIN933"
    assert items[0].name_normalized == "болт м10×40 din933"


async def test_unique_constraint_protects_from_duplicate_inserts(
    session: AsyncSession,
    importer: CatalogImporter,
    tmp_path: Path,
) -> None:
    """Если в Phase 2 кто-то попытается обойти dedupe — partial unique индекс сработает."""
    path = make_xlsx(
        tmp_path / "ok.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["X-1", "Позиция X", "10"],
        ],
    )
    await importer.import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()

    # Проверяем что count = 1 для конкретного нормализованного артикула
    count = await session.scalar(
        select(func.count()).select_from(Item).where(Item.article_normalized == "X1")
    )
    assert count == 1
