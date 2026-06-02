"""Регрессионный тест: REPLACE-импорт каталога можно делать многократно.

См. инцидент 2026-05-29: партиал-уникальный индекс из 0002 не учитывал
is_active, и повторный REPLACE с теми же артикулами падал на UniqueViolation.
Миграция 0004 переделала индекс с условием AND is_active=true.

Поведение REPLACE после рефакторинга 2026-06-02 (UX-фидбэк про дубли при
re-import): REPLACE использует upsert — существующие позиции с тем же
composite-ключом обновляются in-place (сохраняют ID), не создаются дубли.
Поэтому если файл идентичен — все 3 строки uploads = updated, не imported.
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
    """Re-import того же файла = upsert, ID сохраняются, дубли не создаются."""
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
    assert report1.rows_updated == 0
    assert report1.rows_deactivated == 0

    first_ids = {
        i.article_normalized: i.id
        for i in (await session.scalars(select(Item))).all()
    }

    # Второй импорт того же файла — все 3 строки = upsert по composite-ключу
    report2 = await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()
    assert report2.rows_imported == 0  # ничего нового
    assert report2.rows_updated == 3   # все три обновились
    assert report2.rows_deactivated == 0  # ничего не пропало из файла

    # В БД ровно 3 строки, все active, с теми же ID — нет дублей
    items = (await session.scalars(select(Item))).all()
    assert len(items) == 3
    assert all(i.is_active for i in items)
    second_ids = {i.article_normalized: i.id for i in items}
    assert first_ids == second_ids, "ID должны сохраняться при re-import"


async def test_replace_three_times_in_a_row(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Три повтора подряд — ровно 1 строка, все upsert (никаких дублей)."""
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
    assert len(items) == 1  # 3 ре-импорта = всё ещё 1 запись
    assert items[0].is_active


async def test_replace_with_removed_items_deactivates_them(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """REPLACE: позиции которые ИСЧЕЗЛИ из нового файла → deactivate."""
    full = make_xlsx(
        tmp_path / "v1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Первая", "10"],
            ["A-2", "Вторая", "20"],
            ["A-3", "Третья", "30"],
        ],
    )
    await CatalogImporter().import_file(session, full, mode=ImportMode.REPLACE)
    await session.commit()

    # Второй файл — без A-2 (исчезла)
    short = make_xlsx(
        tmp_path / "v2.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Первая", "10"],
            ["A-3", "Третья", "30"],
        ],
    )
    report = await CatalogImporter().import_file(session, short, mode=ImportMode.REPLACE)
    await session.commit()

    assert report.rows_updated == 2  # A-1, A-3
    assert report.rows_deactivated == 1  # A-2 убрана

    by_art = {
        i.article_normalized: i for i in (await session.scalars(select(Item))).all()
    }
    assert by_art["A1"].is_active
    assert by_art["A3"].is_active
    assert not by_art["A2"].is_active  # deactivated


async def test_replace_returning_item_reactivates(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Если позиция была deactivated и вернулась в новом файле — re-активация
    с СОХРАНЕНИЕМ ID (важно для match_candidate FK)."""
    initial = make_xlsx(
        tmp_path / "v1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Первая", "10"],
        ],
    )
    await CatalogImporter().import_file(session, initial, mode=ImportMode.REPLACE)
    await session.commit()
    original_id = (await session.scalar(select(Item))).id

    # Файл без A-1 → A-1 деактивируется
    empty = make_xlsx(
        tmp_path / "v2.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["B-1", "Другая", "100"],
        ],
    )
    await CatalogImporter().import_file(session, empty, mode=ImportMode.REPLACE)
    await session.commit()

    # A-1 вернулась в третий файл
    returning = make_xlsx(
        tmp_path / "v3.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["A-1", "Первая обновлённая", "15"],
        ],
    )
    await CatalogImporter().import_file(session, returning, mode=ImportMode.REPLACE)
    await session.commit()

    a1 = await session.scalar(select(Item).where(Item.article_normalized == "A1"))
    assert a1.id == original_id, "ID должен сохраниться — для FK от match_candidate"
    assert a1.is_active
    assert a1.name == "Первая обновлённая"
