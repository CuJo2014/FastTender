"""End-to-end тесты MatchingEngine на реальной БД с импортированными данными."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import Supplier
from fasttender.models.enums import MatchType
from fasttender.repositories.pg_trgm import PgTrgmSearchRepository
from fasttender.services.importer import CatalogImporter, ImportMode, PriceListImporter
from fasttender.services.matcher import MatchingEngine, MatchInput
from tests.fixtures.spec_builders import make_xlsx


@pytest.fixture
def engine_factory(session: AsyncSession):  # type: ignore[no-untyped-def]
    def _make() -> MatchingEngine:
        return MatchingEngine(PgTrgmSearchRepository(session))

    return _make


async def _seed_dataset(session: AsyncSession, tmp_path: Path) -> Supplier:
    """Каталог + один прайс поставщика, один общий артикул (BLT-M10-040-ZN)."""
    catalog = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Производитель", "Ед.", "Цена"],
            ["BLT-M10-040-ZN", "Болт М10х40 DIN933 оцинкованный", "KOELNER", "шт", "12.50"],
            ["BLT-M10-050-ZN", "Болт М10х50 DIN933 оцинкованный", "KOELNER", "шт", "14.80"],
            ["NUT-M10", "Гайка М10 DIN934 оцинкованная", "KOELNER", "шт", "4.20"],
            ["WSH-M10", "Шайба плоская М10 DIN125", "KOELNER", "шт", "1.10"],
            ["CATALOG-ONLY-001", "Только в каталоге", "OEM", "шт", "100.00"],
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
            ["BLT-M10-040-ZN", "Болт М10х40 (от поставщика)", "11.00"],  # общий
            ["SUPPLIER-ONLY-001", "Только у поставщика", "50.00"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=pricelist, mode=ImportMode.REPLACE
    )
    await session.commit()
    return supplier


# --- Сценарии матчинга ---


async def test_exact_article_hits_both_catalog_and_pricelist(
    session: AsyncSession,
    engine_factory,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """Точное совпадение артикула, который есть и в каталоге, и у поставщика."""
    await _seed_dataset(session, tmp_path)
    engine = engine_factory()

    result = await engine.match(
        MatchInput(
            line_number=1,
            name="Болт М10х40",
            name_normalized="болт м10х40",
            article="BLT-M10-040-ZN",
            article_normalized="BLTM10040ZN",
        )
    )

    # Каталог и прайс — оба нашли
    assert len(result.catalog) == 1
    assert len(result.suppliers) == 1

    cat_top = result.catalog[0]
    sup_top = result.suppliers[0]

    assert cat_top.confidence >= 0.95
    assert cat_top.primary_match_type is MatchType.EXACT_ARTICLE
    assert "Болт М10х40 DIN933" in cat_top.name

    assert sup_top.confidence >= 0.95
    assert sup_top.primary_match_type is MatchType.EXACT_ARTICLE
    assert "от поставщика" in sup_top.name


async def test_fuzzy_article_one_char_typo(
    session: AsyncSession,
    engine_factory,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """Опечатка в артикуле (1 символ) → FUZZY_ARTICLE с приличной confidence."""
    await _seed_dataset(session, tmp_path)
    engine = engine_factory()

    # BLTM10040ZN → BLTM1OO40ZN (O вместо 0 дважды) — должно сматчиться через fuzzy
    result = await engine.match(
        MatchInput(
            line_number=1,
            name="Болт М10х40",
            name_normalized="болт м10х40",
            article="BLT-M1O-O40-ZN",
            article_normalized="BLTM1OO40ZN",
        )
    )

    assert len(result.catalog) >= 1
    top = result.catalog[0]
    # Не exact (но через лексический поиск тоже мог попасть)
    assert top.primary_match_type in {MatchType.FUZZY_ARTICLE, MatchType.LEXICAL}
    assert top.confidence > 0.3
    # Один из ожидаемых артикулов
    assert top.article == "BLT-M10-040-ZN" or "Болт М10х40" in top.name


async def test_name_only_lexical_match(
    session: AsyncSession,
    engine_factory,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """Только наименование, без артикула → лексический поиск."""
    await _seed_dataset(session, tmp_path)
    engine = engine_factory()

    result = await engine.match(
        MatchInput(
            line_number=1,
            name="Болт оцинкованный М10",
            name_normalized="болт оцинкованный м10",
        )
    )

    assert len(result.catalog) >= 1
    top = result.catalog[0]
    assert top.primary_match_type is MatchType.LEXICAL
    assert "Болт" in top.name
    # Confidence лексики обычно 0.3-0.85 (с учётом нашего нормализованного ts_rank)
    assert 0.2 < top.confidence < 0.9


async def test_completely_unknown_item_returns_empty(
    session: AsyncSession,
    engine_factory,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    await _seed_dataset(session, tmp_path)
    engine = engine_factory()

    result = await engine.match(
        MatchInput(
            line_number=1,
            name="Совершенно непохожий товар xyz",
            name_normalized="совершенно непохожий товар xyz",
            article="ZZZ-NONEXISTENT-999",
            article_normalized="ZZZNONEXISTENT999",
        )
    )

    # Может вернуть слабые совпадения по части слов (например, «болт» по «непохожий товар»),
    # но топ-кандидат точно не должен иметь высокий confidence
    if result.catalog:
        assert result.catalog[0].confidence < 0.5


async def test_catalog_only_article_not_in_suppliers(
    session: AsyncSession,
    engine_factory,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """Артикул из каталога, отсутствующий у поставщиков, даёт каталог-hit и пустой suppliers."""
    await _seed_dataset(session, tmp_path)
    engine = engine_factory()

    result = await engine.match(
        MatchInput(
            line_number=1,
            name="Только в каталоге",
            name_normalized="только в каталоге",
            article="CATALOG-ONLY-001",
            article_normalized="CATALOGONLY001",
        )
    )

    assert len(result.catalog) == 1
    assert result.catalog[0].confidence >= 0.95
    assert result.suppliers == []


async def test_supplier_only_article(
    session: AsyncSession,
    engine_factory,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """Артикул только у поставщика — supplier hit, catalog empty."""
    await _seed_dataset(session, tmp_path)
    engine = engine_factory()

    result = await engine.match(
        MatchInput(
            line_number=1,
            name="Только у поставщика",
            name_normalized="только у поставщика",
            article="SUPPLIER-ONLY-001",
            article_normalized="SUPPLIERONLY001",
        )
    )

    assert result.catalog == []
    assert len(result.suppliers) == 1
    assert result.suppliers[0].confidence >= 0.95


async def test_match_many_processes_full_spec(
    session: AsyncSession,
    engine_factory,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """match_many возвращает MatchResult в том же порядке для каждой строки."""
    await _seed_dataset(session, tmp_path)
    engine = engine_factory()

    inputs = [
        MatchInput(
            line_number=1,
            name="Болт",
            name_normalized="болт",
            article="BLT-M10-040-ZN",
            article_normalized="BLTM10040ZN",
        ),
        MatchInput(
            line_number=2,
            name="Гайка",
            name_normalized="гайка",
            article="NUT-M10",
            article_normalized="NUTM10",
        ),
        MatchInput(
            line_number=3,
            name="Несуществующий",
            name_normalized="несуществующий",
            article="ZZZ-NONE",
            article_normalized="ZZZNONE",
        ),
    ]

    results = await engine.match_many(inputs)
    assert len(results) == 3
    assert results[0].spec_item_line == 1
    assert results[1].spec_item_line == 2
    assert results[2].spec_item_line == 3

    assert results[0].catalog[0].confidence >= 0.95
    assert results[1].catalog[0].confidence >= 0.95
    # Третья позиция — либо нет в каталоге, либо слабый лексический
    if results[2].catalog:
        assert results[2].catalog[0].confidence < 0.5


async def test_code_in_name_and_brand_boost_from_attributes(
    session: AsyncSession,
    engine_factory,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """Задачи 2-3: код модели зашит в ИМЯ каталога (артикул пуст), бренд —
    в характеристике клиента. Позиция с кодом+брендом должна обойти общую."""
    catalog = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Производитель", "Ед.", "Цена"],
            ["", "Домкрат гидравлический ДГ15-3913010-03", "ШААЗ", "шт", "1000"],
            ["", "Домкрат гидравлический бутылочный 3т Matrix", "Matrix", "шт", "900"],
        ],
    )
    await CatalogImporter().import_file(session, catalog, mode=ImportMode.REPLACE)
    await session.commit()
    engine = engine_factory()

    # Как построит адаптер: имя + характеристика «5т Д1-3913010-50 ШААЗ»
    result = await engine.match(
        MatchInput(
            line_number=1,
            name="Гидравлический домкрат бутылочный",
            name_normalized="гидравлический домкрат бутылочный 5т д1-3913010-50 шааз",
            article_normalized=None,
            code_tokens=("3913010",),
        ),
        top_n=5,
    )

    assert result.catalog, "ожидали кандидатов из каталога"
    top = result.catalog[0]
    # Победила позиция ШААЗ с кодом в имени
    assert "3913010" in top.name
    assert top.explanation.extracted_code_match == "in_name"
    assert top.explanation.brand_match is True
