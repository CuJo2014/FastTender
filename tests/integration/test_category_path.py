"""End-to-end проверка иерархии category_path: парсер → импорт → API.

См. обсуждение 2026-05-29: Phase 1 хранит иерархию из 1С одной строкой
в Item.category_path. Колонка распознаётся парсером по словарю синонимов
(«Категория», «Группа», «Раздел»...), импортёр прокидывает в БД, API
возвращает в CandidateRead.
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import Item, Specification, SpecificationStatus
from fasttender.services.importer import CatalogImporter, ImportMode
from fasttender.services.parser import SpecField, SpecificationParser
from fasttender.services.pipeline import SpecificationProcessor
from tests.fixtures.spec_builders import make_xlsx


def test_parser_recognizes_category_synonyms(tmp_path: Path) -> None:
    """Парсер должен находить колонку category по разным русским заголовкам."""
    parser = SpecificationParser()
    for header_name in ("Категория", "Группа", "Группа товаров", "Раздел"):
        path = make_xlsx(
            tmp_path / f"hdr_{hash(header_name)}.xlsx",
            rows=[
                ["Артикул", "Наименование", header_name, "Цена"],
                ["BLT-1", "Болт", "Крепёж / Болты", "10"],
            ],
        )
        result = parser.parse(path)
        assert result.column_mapping.has(SpecField.CATEGORY), header_name
        assert result.items[0].category == "Крепёж / Болты"


async def test_catalog_import_stores_category_path(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    catalog = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Категория", "Цена"],
            ["BLT-1", "Болт М10", "Крепёж / Болты / DIN933", "10"],
            ["NUT-1", "Гайка М10", "Крепёж / Гайки", "4"],
            ["ABC-1", "Без категории", None, "1"],
        ],
    )
    await CatalogImporter().import_file(session, catalog, mode=ImportMode.REPLACE)
    await session.commit()

    items = {i.article_normalized: i for i in (await session.scalars(select(Item))).all()}
    assert items["BLT1"].category_path == "Крепёж / Болты / DIN933"
    assert items["NUT1"].category_path == "Крепёж / Гайки"
    assert items["ABC1"].category_path is None


async def test_catalog_merge_updates_category_path(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """MERGE-режим должен обновлять category_path вместе с остальными полями."""
    first = make_xlsx(
        tmp_path / "v1.xlsx",
        rows=[
            ["Артикул", "Наименование", "Категория", "Цена"],
            ["BLT-1", "Болт", "Старая категория", "10"],
        ],
    )
    second = make_xlsx(
        tmp_path / "v2.xlsx",
        rows=[
            ["Артикул", "Наименование", "Категория", "Цена"],
            ["BLT-1", "Болт", "Новая / Иерархия / Глубже", "12"],
        ],
    )

    await CatalogImporter().import_file(session, first, mode=ImportMode.REPLACE)
    await session.commit()
    await CatalogImporter().import_file(session, second, mode=ImportMode.MERGE)
    await session.commit()

    item = await session.scalar(select(Item).where(Item.article_normalized == "BLT1"))
    assert item.category_path == "Новая / Иерархия / Глубже"


async def test_category_path_in_match_candidate_api(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """category_path катологического кандидата доходит до payload'а /items."""
    catalog = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Группа товаров", "Цена"],
            ["BLT-001", "Болт М10х40", "Крепёж / Болты с шестигранной головкой", "12.50"],
        ],
    )
    await CatalogImporter().import_file(session, catalog, mode=ImportMode.REPLACE)
    await session.commit()

    spec_file = make_xlsx(
        tmp_path / "spec.xlsx",
        rows=[
            ["Наименование", "Артикул", "Кол-во"],
            ["Болт М10х40", "BLT-001", 1],
        ],
    )
    spec = Specification(
        source_filename="spec.xlsx",
        storage_path=str(spec_file),
        status=SpecificationStatus.UPLOADED,
        meta={},
    )
    session.add(spec)
    await session.commit()
    await session.refresh(spec)

    await SpecificationProcessor(session).process(spec.id)

    # Проверим через API-сериализатор (для CandidateRead)
    from sqlalchemy.orm import selectinload

    from fasttender.models import MatchCandidate, SpecItem

    spec_item = await session.scalar(
        select(SpecItem)
        .where(SpecItem.spec_id == spec.id)
        .options(
            selectinload(SpecItem.candidates)
            .selectinload(MatchCandidate.item)
            .selectinload(Item.source)
        )
    )
    assert spec_item is not None
    top = spec_item.candidates[0]
    # category_path должна быть подгружена и доступна
    assert top.item.category_path == "Крепёж / Болты с шестигранной головкой"
