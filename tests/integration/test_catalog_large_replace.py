"""Регрессия 2026-06-05: REPLACE-импорт каталога с числом строк больше лимита
bind-параметров PostgreSQL/asyncpg (32767) падал с InterfaceError на
`code_1c IN (...)` (lookup существующих) и `id NOT IN (...)` (деактивация).

Причина: после рефакторинга 2026-06-02 (`f14d946`, upsert вместо
deactivate-all+insert) появились IN/NOT IN со списком на весь файл. Каталог
компании ~97K строк > 32767 → лимит. Раньше (до рефакторинга) грузилось
через bulk-insert, который asyncpg сам бьёт на батчи.

Фикс: lookup'ы и деактивация бьются на батчи (`_PARAM_CHUNK`). Здесь форсируем
многобатчевый путь, уменьшая чанк до 2 — чтобы не плодить 33К строк в тесте,
но пройти ровно те же ветки кода через границы батчей.
"""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import Item
from fasttender.services.importer import CatalogImporter, ImportMode, _base
from tests.fixtures.spec_builders import make_xlsx


async def test_replace_spans_multiple_param_batches(
    session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Чанк = 2, файл из 5 строк по code_1c → lookup и deactivate идут
    несколькими батчами. Проверяем корректность через границы батчей:
    нет дублей, ID сохраняются, исчезнувшие деактивируются."""
    monkeypatch.setattr(_base, "_PARAM_CHUNK", 2)

    v1 = make_xlsx(
        tmp_path / "v1.xlsx",
        rows=[
            ["Код 1С", "Наименование", "Цена"],
            *[[f"K-{n}", f"Имя {n}", "10"] for n in range(1, 6)],  # K-1..K-5
        ],
    )
    report1 = await CatalogImporter().import_file(session, v1, mode=ImportMode.REPLACE)
    await session.commit()
    assert report1.rows_imported == 5
    assert report1.rows_updated == 0
    assert report1.rows_deactivated == 0

    ids_v1 = {i.code_1c: i.id for i in (await session.scalars(select(Item))).all()}
    assert len(ids_v1) == 5

    # v2: K-1..K-4 с новыми именами, K-5 исчез, добавлен K-6
    v2 = make_xlsx(
        tmp_path / "v2.xlsx",
        rows=[
            ["Код 1С", "Наименование", "Цена"],
            *[[f"K-{n}", f"Имя {n} обновл", "11"] for n in range(1, 5)],  # K-1..K-4
            ["K-6", "Имя 6", "12"],
        ],
    )
    report2 = await CatalogImporter().import_file(session, v2, mode=ImportMode.REPLACE)
    await session.commit()

    assert report2.rows_imported == 1     # K-6
    assert report2.rows_updated == 4      # K-1..K-4
    assert report2.rows_deactivated == 1  # K-5 исчез

    items = {i.code_1c: i for i in (await session.scalars(select(Item))).all()}
    assert len(items) == 6, "дублей быть не должно — 6 уникальных code_1c"
    for n in range(1, 5):
        code = f"K-{n}"
        assert items[code].id == ids_v1[code], "ID сохраняется при upsert"
        assert items[code].is_active
        assert items[code].name == f"Имя {n} обновл"
    assert not items["K-5"].is_active  # исчез → деактивирован
    assert items["K-6"].is_active      # новый
