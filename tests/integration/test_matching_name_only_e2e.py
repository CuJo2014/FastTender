"""E2E матчинга для клиентских спек БЕЗ колонки артикула (диагностика
«нулевого» матчинга 2026-06-05).

Point 1: name-only совпадение больше не упирается в потолок ~0.5 — корректный
матч попадает в зону ручной проверки (≥ 0.5), а не в «Не найдено».
Point 2: код/модель, зашитые в наименование, извлекаются и матчатся по
article каталога, давая буст.
"""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.repositories.pg_trgm import PgTrgmSearchRepository
from fasttender.services.importer import CatalogImporter, ImportMode
from fasttender.services.matcher import MatchingEngine, MatchInput
from fasttender.services.parser.value_normalizer import (
    extract_article_candidates,
    normalize_name,
)
from tests.fixtures.spec_builders import make_xlsx


async def _seed_catalog(session: AsyncSession, tmp_path: Path) -> None:
    catalog = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["BLT-M10-040-ZN", "Болт М10х40 DIN933 оцинкованный", "12.50"],
            # Артикул каталога = код, который встретится внутри имени спеки
            ["2342380", "Пылесос строительный Einhell TE-VC 2340 SA", "8500.00"],
        ],
    )
    await CatalogImporter().import_file(session, catalog, mode=ImportMode.REPLACE)
    await session.commit()


async def test_name_only_match_surfaces_into_review_band(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Point 1: сильный name-only матч даёт confidence ≥ 0.5 (раньше ~0.4)."""
    await _seed_catalog(session, tmp_path)
    engine = MatchingEngine(PgTrgmSearchRepository(session))

    name = "Болт М10х40 DIN933 оцинкованный"
    result = await engine.match(
        MatchInput(line_number=1, name=name, name_normalized=normalize_name(name))
    )

    assert result.catalog, "должен найтись каталог-кандидат"
    top = result.catalog[0]
    assert "Болт М10х40" in top.name
    # Ключевое: корректный матч больше НЕ прячется в «Не найдено» (<0.5)
    assert top.confidence >= 0.5


async def test_embedded_code_extracted_and_boosts(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Point 2: код «2342380» из имени совпадает с article каталога → буст."""
    await _seed_catalog(session, tmp_path)
    engine = MatchingEngine(PgTrgmSearchRepository(session))

    name = "Пылесос Einhell TE-VC 2340 SA 2342380"
    candidates = extract_article_candidates(name)
    assert "2342380" in candidates  # извлеклось

    result = await engine.match(
        MatchInput(
            line_number=1,
            name=name,
            name_normalized=normalize_name(name),
            article_candidates=tuple(candidates),
        )
    )

    assert result.catalog
    top = result.catalog[0]
    assert top.article == "2342380"
    assert top.explanation.extracted_code_match == "exact"
    assert top.explanation.extracted_code == "2342380"
    # имя близко + точный код → уверенно в зоне проверки
    assert top.confidence >= 0.5


async def test_no_code_in_plain_name_no_extraction(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Имя без кодов → article_candidates пуст, поведение как раньше (только лексика)."""
    await _seed_catalog(session, tmp_path)
    engine = MatchingEngine(PgTrgmSearchRepository(session))

    name = "Болт оцинкованный"
    assert extract_article_candidates(name) == []
    result = await engine.match(
        MatchInput(line_number=1, name=name, name_normalized=normalize_name(name))
    )
    # Находит болт лексически, без падений
    assert result.catalog
    assert result.catalog[0].explanation.extracted_code_match == "none"
