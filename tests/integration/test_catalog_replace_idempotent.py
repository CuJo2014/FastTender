"""Регрессионный тест: REPLACE-импорт каталога можно делать многократно.

См. инцидент 2026-05-29: партиал-уникальный индекс из 0002 не учитывал
is_active, и повторный REPLACE с теми же артикулами падал на UniqueViolation.
Миграция 0004 переделала индекс с условием AND is_active=true.

Этот тест проверяет инвариант: «REPLACE дважды подряд с пересекающимися
артикулами оставляет в БД только новый срез активным, старый деактивирован».
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import Item
from fasttender.services.importer import CatalogImporter, ImportMode
from tests.fixtures.spec_builders import make_xlsx


async def test_replace_twice_with_same_articles_succeeds(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Каталог с теми же артикулами можно перезалить REPLACE без UniqueViolation."""
    rows = [
        ["Артикул", "Наименование", "Цена"],
        ["A-1", "Позиция 1", "10"],
        ["A-2", "Позиция 2", "20"],
        ["A-3", "Позиция 3", "30"],
    ]
    path = make_xlsx(tmp_path / "catalog.xlsx", rows=rows)

    # Первый импорт
    report1 = await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()
    assert report1.rows_imported == 3
    assert report1.rows_deactivated == 0

    # Второй импорт того же файла — раньше падал на UniqueViolation
    report2 = await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()
    assert report2.rows_imported == 3
    assert report2.rows_deactivated == 3  # старые помечены неактивными

    # В БД 6 строк: 3 деактивированных + 3 активных
    items = (
        await session.scalars(select(Item).order_by(Item.article_normalized, Item.is_active))
    ).all()
    assert len(items) == 6
    active = [i for i in items if i.is_active]
    deactivated = [i for i in items if not i.is_active]
    assert len(active) == 3
    assert len(deactivated) == 3
    # Каждый артикул представлен ровно одной активной и одной деактивированной
    assert {i.article_normalized for i in active} == {"A1", "A2", "A3"}
    assert {i.article_normalized for i in deactivated} == {"A1", "A2", "A3"}


async def test_replace_three_times_in_a_row(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Три повтора подряд — должно быть 1 активная + 2 деактивированные на каждый артикул."""
    path = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["X-1", "Позиция X", "10"],
        ],
    )
    for _ in range(3):
        await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
        await session.commit()

    items = (await session.scalars(select(Item))).all()
    assert len(items) == 3
    actives = [i for i in items if i.is_active]
    assert len(actives) == 1
