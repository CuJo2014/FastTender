"""Интеграционные тесты PgTrgmSearchRepository против реального Postgres."""

from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import DataSource, DataSourceType, Item, Supplier
from fasttender.models.enums import MatchType
from fasttender.repositories.pg_trgm import PgTrgmSearchRepository
from fasttender.repositories.search import SourceFilter
from fasttender.services.importer import CatalogImporter, ImportMode, PriceListImporter
from tests.fixtures.spec_builders import make_xlsx


@pytest.fixture
def repo(session: AsyncSession) -> PgTrgmSearchRepository:
    return PgTrgmSearchRepository(session)


async def _seed_catalog(session: AsyncSession, tmp_path: Path) -> None:
    """Заполняет каталог 10 позициями для теста."""
    path = make_xlsx(
        tmp_path / "catalog.xlsx",
        rows=[
            ["Артикул", "Наименование", "Производитель", "Ед.", "Цена"],
            ["BLT-M10-040-ZN", "Болт М10х40 DIN933 оцинкованный", "KOELNER", "шт", "12.50"],
            ["BLT-M10-050-ZN", "Болт М10х50 DIN933 оцинкованный", "KOELNER", "шт", "14.80"],
            ["BLT-M12-040", "Болт М12х40 DIN933", "KOELNER", "шт", "18.20"],
            ["NUT-M10", "Гайка М10 DIN934 оцинкованная", "KOELNER", "шт", "4.20"],
            ["NUT-M12", "Гайка М12 DIN934", "KOELNER", "шт", "5.10"],
            ["WSH-M10", "Шайба плоская М10 DIN125", "KOELNER", "шт", "1.10"],
            ["WSH-M12", "Шайба плоская М12 DIN125", "KOELNER", "шт", "1.40"],
            ["WSH-M10-SPR", "Шайба пружинная М10 DIN127", "KOELNER", "шт", "1.30"],
            ["DOWEL-6-40", "Дюбель универсальный 6х40", "FISCHER", "шт", "2.50"],
            ["DOWEL-8-50", "Дюбель универсальный 8х50", "FISCHER", "шт", "3.80"],
        ],
    )
    await CatalogImporter().import_file(session, path, mode=ImportMode.REPLACE)
    await session.commit()


# --- search_by_article (exact) ---


async def test_exact_article_finds_single_hit(
    session: AsyncSession,
    repo: PgTrgmSearchRepository,
    tmp_path: Path,
) -> None:
    await _seed_catalog(session, tmp_path)

    # Artikul нормализуется как "BLTM10040ZN"
    hits = await repo.search_by_article("BLTM10040ZN", exact=True)
    assert len(hits) == 1
    assert hits[0].score == 1.0
    assert hits[0].match_type is MatchType.EXACT_ARTICLE
    assert hits[0].name == "Болт М10х40 DIN933 оцинкованный"


async def test_exact_article_returns_empty_for_unknown(
    session: AsyncSession,
    repo: PgTrgmSearchRepository,
    tmp_path: Path,
) -> None:
    await _seed_catalog(session, tmp_path)
    hits = await repo.search_by_article("NONEXISTENT", exact=True)
    assert hits == []


# --- search_by_article (fuzzy) ---


async def test_fuzzy_article_finds_typo(
    session: AsyncSession,
    repo: PgTrgmSearchRepository,
    tmp_path: Path,
) -> None:
    """1-символьная опечатка должна сматчиться с высокой similarity."""
    await _seed_catalog(session, tmp_path)

    # Правильный артикул: BLTM10040ZN (после normalize_article из BLT-M10-040-ZN)
    # Опечатка: BLTM10O40ZN (O вместо 0 в "040")
    hits = await repo.search_by_article("BLTM10O40ZN", exact=False, min_similarity=0.5)
    assert len(hits) >= 1
    first = hits[0]
    assert first.article_normalized == "BLTM10040ZN"
    assert first.match_type is MatchType.FUZZY_ARTICLE
    assert 0.5 < first.score < 1.0


async def test_fuzzy_respects_min_similarity(
    session: AsyncSession,
    repo: PgTrgmSearchRepository,
    tmp_path: Path,
) -> None:
    await _seed_catalog(session, tmp_path)

    # Совершенно непохожий артикул — даже с низким порогом ничего не должно найтись
    hits = await repo.search_by_article("XYZ123ABC", exact=False, min_similarity=0.5)
    assert hits == []


# --- search_lexical ---


async def test_lexical_finds_via_russian_morphology(
    session: AsyncSession,
    repo: PgTrgmSearchRepository,
    tmp_path: Path,
) -> None:
    """tsvector с 'russian' dictionary должен матчить разные формы слова.

    «оцинкованный» в запросе → должен найти позиции, содержащие «оцинков»
    в названии (морфология русского словаря).
    """
    await _seed_catalog(session, tmp_path)

    hits = await repo.search_lexical("болт оцинкованный")
    assert len(hits) >= 2  # есть как минимум 2 болта оцинкованных
    names = [h.name for h in hits[:3]]
    # Топ-результаты — про болты оцинкованные
    assert any("Болт" in n and "оцинкован" in n for n in names)


async def test_lexical_uses_trigram_fallback_on_typo(
    session: AsyncSession,
    repo: PgTrgmSearchRepository,
    tmp_path: Path,
) -> None:
    """Опечатка в наименовании всё равно даёт результат через trigram."""
    await _seed_catalog(session, tmp_path)

    # "шайбя" вместо "шайба" — tsvector не найдёт, но trigram должен
    hits = await repo.search_lexical("шайбя плоская м10")
    assert len(hits) >= 1
    # Топ — какая-то шайба
    assert "айб" in hits[0].name.lower()


async def test_lexical_score_in_unit_range(
    session: AsyncSession,
    repo: PgTrgmSearchRepository,
    tmp_path: Path,
) -> None:
    """score лексического поиска нормализован в [0, 1]."""
    await _seed_catalog(session, tmp_path)

    hits = await repo.search_lexical("болт оцинкованный")
    for hit in hits:
        assert 0.0 <= hit.score <= 1.0
        assert hit.match_type is MatchType.LEXICAL


# --- SourceFilter ---


async def test_source_filter_by_type_catalog_only(
    session: AsyncSession,
    repo: PgTrgmSearchRepository,
    tmp_path: Path,
) -> None:
    """SourceFilter(types=[COMPANY_CATALOG]) исключает прайсы поставщиков."""
    await _seed_catalog(session, tmp_path)

    # Добавляем прайс одного поставщика с тем же артикулом
    supplier = Supplier(name="Test Supplier", meta={})
    session.add(supplier)
    await session.flush()
    pl_path = make_xlsx(
        tmp_path / "pl.xlsx",
        rows=[
            ["Артикул", "Наименование", "Цена"],
            ["BLT-M10-040-ZN", "Болт М10х40 (поставщик)", "11.00"],
        ],
    )
    await PriceListImporter().import_file(
        session, supplier_id=supplier.id, path=pl_path, mode=ImportMode.REPLACE
    )
    await session.commit()

    # Без фильтра — оба источника
    all_hits = await repo.search_by_article("BLTM10040ZN", exact=True)
    assert len(all_hits) == 2

    # С фильтром — только каталог
    catalog_only = await repo.search_by_article(
        "BLTM10040ZN",
        exact=True,
        source_filter=SourceFilter(types=(DataSourceType.COMPANY_CATALOG,)),
    )
    assert len(catalog_only) == 1
    assert catalog_only[0].source_type is DataSourceType.COMPANY_CATALOG

    # С фильтром по supplier_id — только этот поставщик
    supplier_only = await repo.search_by_article(
        "BLTM10040ZN",
        exact=True,
        source_filter=SourceFilter(supplier_ids=(supplier.id,)),
    )
    assert len(supplier_only) == 1
    assert supplier_only[0].source_type is DataSourceType.SUPPLIER_PRICELIST


async def test_source_filter_only_active_excludes_deactivated(
    session: AsyncSession,
    repo: PgTrgmSearchRepository,
    tmp_path: Path,
) -> None:
    """is_active=false исключается из поиска по умолчанию."""
    await _seed_catalog(session, tmp_path)

    # Деактивируем один Item
    item = await session.scalar(select(Item).where(Item.article_normalized == "BLTM10040ZN"))
    assert item is not None
    await session.execute(update(Item).where(Item.id == item.id).values(is_active=False))
    await session.commit()

    hits = await repo.search_by_article("BLTM10040ZN", exact=True)
    assert hits == []

    # Но если выключить only_active — найдётся
    hits = await repo.search_by_article(
        "BLTM10040ZN",
        exact=True,
        source_filter=SourceFilter(only_active=False),
    )
    assert len(hits) == 1


async def test_source_filter_excludes_paused_source(
    session: AsyncSession,
    repo: PgTrgmSearchRepository,
    tmp_path: Path,
) -> None:
    """DataSource.status='paused' тоже исключается при only_active=True."""
    await _seed_catalog(session, tmp_path)

    # Ставим каталог на паузу
    source = await session.scalar(
        select(DataSource).where(DataSource.type == DataSourceType.COMPANY_CATALOG)
    )
    assert source is not None
    source.status = source.status.__class__("paused")
    await session.commit()

    hits = await repo.search_by_article("BLTM10040ZN", exact=True)
    assert hits == []
