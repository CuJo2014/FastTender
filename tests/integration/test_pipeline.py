"""Интеграционные тесты SpecificationProcessor.

Тестируем pipeline напрямую (не через Celery): processor сам по себе
async, и его поведение проще верифицировать без брокера.
Целочисленный тест с Celery в eager-режиме — отдельно в test_celery_task.py.
"""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fasttender.models import (
    DataSourceType,
    Item,
    MatchCandidate,
    Specification,
    SpecificationStatus,
    SpecItem,
    Supplier,
)
from fasttender.models.enums import MatchType
from fasttender.services.importer import CatalogImporter, ImportMode, PriceListImporter
from fasttender.services.parser import ParseError
from fasttender.services.pipeline import SpecificationProcessor
from tests.fixtures.spec_builders import make_xlsx


async def _seed_catalog_and_pricelist(session: AsyncSession, tmp_path: Path) -> Supplier:
    catalog = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Производитель", "Ед.", "Цена"],
            ["BLT-M10-040", "Болт М10х40 DIN933 оцинкованный", "KOELNER", "шт", "12.50"],
            ["NUT-M10", "Гайка М10 DIN934", "KOELNER", "шт", "4.20"],
            ["WSH-M10", "Шайба плоская М10 DIN125", "KOELNER", "шт", "1.10"],
        ],
    )
    await CatalogImporter().import_file(session, catalog, mode=ImportMode.REPLACE)
    await session.commit()

    supplier = Supplier(name="ООО Поставщик-1", meta={})
    session.add(supplier)
    await session.flush()

    pricelist = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["BLT-M10-040", "Болт М10х40 от поставщика", "11.00"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=pricelist, mode=ImportMode.REPLACE
    )
    await session.commit()
    return supplier


async def _create_spec_from_file(session: AsyncSession, file_path: Path) -> Specification:
    spec = Specification(
        source_filename=file_path.name,
        storage_path=str(file_path),
        client_name="Тест-Клиент",
        status=SpecificationStatus.UPLOADED,
        meta={},
    )
    session.add(spec)
    await session.commit()
    await session.refresh(spec)
    return spec


# --- Полный happy-path ---


async def test_happy_path_processes_spec_end_to_end(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    await _seed_catalog_and_pricelist(session, tmp_path)

    spec_file = make_xlsx(
        tmp_path / "spec.xlsx",
        rows=[
            ["Наименование", "Артикул", "Кол-во", "Ед."],
            ["Болт М10х40", "BLT-M10-040", 50, "шт"],
            ["Гайка М10", "NUT-M10", 100, "шт"],
            ["Что-то непонятное", "UNKNOWN-999", 1, "шт"],
        ],
    )
    spec = await _create_spec_from_file(session, spec_file)

    processor = SpecificationProcessor(session)
    await processor.process(spec.id)

    # Статус после успешной обработки
    await session.refresh(spec)
    # После матчинга — REVIEWING (требует верификации), не MATCHED.
    # Изменено по UX-фидбэку 1 июня 2026.
    assert spec.status is SpecificationStatus.REVIEWING
    assert spec.completed_at is not None
    assert spec.error_message is None

    # Создались SpecItem
    spec_items = (
        await session.scalars(
            select(SpecItem).where(SpecItem.spec_id == spec.id).order_by(SpecItem.line_number)
        )
    ).all()
    assert len(spec_items) == 3

    # Первая строка — нормализация применена
    blt = spec_items[0]
    assert blt.name_raw == "Болт М10х40"
    assert blt.name_normalized == "болт м10х40"
    assert blt.article_raw == "BLT-M10-040"
    assert blt.article_normalized == "BLTM10040"
    assert blt.quantity == 50

    # MatchCandidate-ряды созданы для каждой строки
    candidates = (
        await session.scalars(
            select(MatchCandidate).where(
                MatchCandidate.spec_item_id.in_([si.id for si in spec_items])
            )
        )
    ).all()
    assert len(candidates) >= 2  # как минимум для двух известных артикулов

    # Проверим что для известного артикула есть catalog (rank=1) + supplier (rank=1)
    blt_candidates = [c for c in candidates if c.spec_item_id == blt.id]
    blt_with_items = (
        await session.scalars(
            select(MatchCandidate)
            .where(MatchCandidate.spec_item_id == blt.id)
            .options(selectinload(MatchCandidate.item))
        )
    ).all()
    by_source = {c.item.source_id: c for c in blt_with_items}
    # Минимум два разных source_id — каталог и поставщик
    assert len(by_source) == 2

    # У всех BLT-кандидатов должен быть высокий confidence (exact article)
    for c in blt_candidates:
        assert float(c.confidence) >= 0.95
        assert c.match_type is MatchType.EXACT_ARTICLE


async def test_meta_captures_parse_details(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """В spec.meta попадает результат парсинга — sheet, header_row, mapping."""
    await _seed_catalog_and_pricelist(session, tmp_path)

    spec_file = make_xlsx(
        tmp_path / "spec.xlsx",
        rows=[
            ["Какой-то заголовок", None, None],
            ["Наименование", "Артикул", "Кол-во"],
            ["Болт М10х40", "BLT-M10-040", 50],
        ],
    )
    spec = await _create_spec_from_file(session, spec_file)
    await SpecificationProcessor(session).process(spec.id)

    await session.refresh(spec)
    assert spec.meta.get("header_row") == 1
    assert spec.meta.get("sheet_name") == "Спецификация"
    assert "column_mapping" in spec.meta
    assert spec.meta["column_mapping"]["name"] == 0
    assert spec.meta["column_mapping"]["article"] == 1


# --- Ошибки ---


async def test_parse_failure_sets_status_and_message(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Файл без узнаваемой шапки → PARSE_FAILED + error_message."""
    bad_file = make_xlsx(
        tmp_path / "bad.xlsx",
        rows=[
            ["xxx", "yyy", "zzz"],
            ["abc", "def", "ghi"],
        ],
    )
    spec = await _create_spec_from_file(session, bad_file)

    with pytest.raises(ParseError):
        await SpecificationProcessor(session).process(spec.id)

    await session.refresh(spec)
    assert spec.status is SpecificationStatus.PARSE_FAILED
    assert spec.error_message is not None
    assert "шапк" in spec.error_message.lower()


async def test_missing_file_sets_failed_status(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    spec = Specification(
        source_filename="missing.xlsx",
        storage_path=str(tmp_path / "does_not_exist.xlsx"),
        status=SpecificationStatus.UPLOADED,
        meta={},
    )
    session.add(spec)
    await session.commit()
    await session.refresh(spec)

    with pytest.raises(ParseError):
        await SpecificationProcessor(session).process(spec.id)

    await session.refresh(spec)
    assert spec.status is SpecificationStatus.PARSE_FAILED
    assert spec.error_message is not None


# --- Идемпотентность повторного запуска ---


async def test_reprocess_replaces_spec_items(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Повторный запуск пайплайна очищает старые SpecItem и MatchCandidate."""
    await _seed_catalog_and_pricelist(session, tmp_path)
    spec_file = make_xlsx(
        tmp_path / "spec.xlsx",
        rows=[
            ["Наименование", "Артикул", "Кол-во"],
            ["Болт М10х40", "BLT-M10-040", 50],
        ],
    )
    spec = await _create_spec_from_file(session, spec_file)

    await SpecificationProcessor(session).process(spec.id)
    first_count = await session.scalar(select(SpecItem).where(SpecItem.spec_id == spec.id))
    assert first_count is not None

    # Повторный запуск
    await SpecificationProcessor(session).process(spec.id)

    spec_items = (await session.scalars(select(SpecItem).where(SpecItem.spec_id == spec.id))).all()
    # Та же одна позиция, не дублирована
    assert len(spec_items) == 1


# --- Топ-N разбит правильно ---


async def test_candidates_split_across_source_types(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Точный артикул должен дать кандидата и из каталога, и от поставщика."""
    await _seed_catalog_and_pricelist(session, tmp_path)
    spec_file = make_xlsx(
        tmp_path / "spec.xlsx",
        rows=[
            ["Наименование", "Артикул", "Кол-во"],
            ["Болт М10х40", "BLT-M10-040", 50],
        ],
    )
    spec = await _create_spec_from_file(session, spec_file)
    await SpecificationProcessor(session).process(spec.id)

    cands = (
        await session.scalars(
            select(MatchCandidate)
            .where(
                MatchCandidate.spec_item_id.in_(
                    select(SpecItem.id).where(SpecItem.spec_id == spec.id)
                )
            )
            .options(selectinload(MatchCandidate.item).selectinload(Item.source))
        )
    ).all()

    source_types = {c.item.source.type for c in cands}
    assert DataSourceType.COMPANY_CATALOG in source_types
    assert DataSourceType.SUPPLIER_PRICELIST in source_types
    # Каждый кандидат имеет валидный explanation
    for c in cands:
        assert "final_score" in c.explanation
        assert "human_readable" in c.explanation
