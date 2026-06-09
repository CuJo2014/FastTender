"""Unit-тесты MatchingEngine с фейковым SearchRepository.

Цель — проверить оркестрацию каскада (раздел 9.1), а не корректность
SQL. SQL тестируется отдельно в integration-тестах.
"""

from decimal import Decimal
from uuid import UUID, uuid4

from fasttender.models.enums import DataSourceType, MatchType
from fasttender.repositories.search import SearchHit, SearchRepository, SourceFilter
from fasttender.services.matcher import MatchingEngine, MatchInput


class FakeSearchRepository(SearchRepository):
    """Подсчитывает вызовы, выдаёт заранее заготовленные ответы."""

    def __init__(
        self,
        *,
        exact_hits: list[SearchHit] | None = None,
        fuzzy_hits: list[SearchHit] | None = None,
        lexical_hits: list[SearchHit] | None = None,
        code_name_hits: list[SearchHit] | None = None,
        brands: set[str] | None = None,
    ) -> None:
        self._exact = exact_hits or []
        self._fuzzy = fuzzy_hits or []
        self._lex = lexical_hits or []
        self._code_name = code_name_hits or []
        self._brands = brands or set()
        self.calls: list[tuple[str, dict]] = []

    async def search_by_article(
        self,
        article: str,
        *,
        exact: bool = False,
        source_filter: SourceFilter | None = None,
        limit: int = 10,
        min_similarity: float = 0.4,
    ) -> list[SearchHit]:
        self.calls.append(("article", {"article": article, "exact": exact, "limit": limit}))
        return self._exact if exact else self._fuzzy

    async def search_lexical(
        self,
        query: str,
        *,
        source_filter: SourceFilter | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        self.calls.append(("lexical", {"query": query, "limit": limit}))
        return self._lex

    async def search_by_code_in_name(
        self,
        code: str,
        *,
        source_filter: SourceFilter | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        self.calls.append(("code_in_name", {"code": code, "limit": limit}))
        return self._code_name

    async def known_manufacturers(
        self,
        *,
        source_filter: SourceFilter | None = None,
    ) -> set[str]:
        return self._brands


def _hit(
    *,
    item_id: UUID | None = None,
    source_type: DataSourceType = DataSourceType.COMPANY_CATALOG,
    score: float = 1.0,
    match_type: MatchType = MatchType.EXACT_ARTICLE,
    name: str = "Болт М10",
    article_normalized: str = "BLT001",
) -> SearchHit:
    return SearchHit(
        item_id=item_id or uuid4(),
        source_id=uuid4(),
        source_type=source_type,
        article_raw=article_normalized,
        article_normalized=article_normalized,
        name=name,
        name_normalized=name.lower(),
        manufacturer=None,
        manufacturer_normalized=None,
        price=Decimal("10"),
        currency="RUB",
        unit="шт",
        score=score,
        match_type=match_type,
    )


def _input(
    *,
    article_normalized: str | None = "BLT001",
    name_normalized: str | None = "болт м10",
) -> MatchInput:
    return MatchInput(
        line_number=1,
        name="Болт М10",
        name_normalized=name_normalized,
        article="BLT-001",
        article_normalized=article_normalized,
    )


# --- Каскад ---


class TestCascade:
    async def test_exact_match_short_circuits(self) -> None:
        """L1 hit → НЕ должен вызывать L2 и L3 (раздел 9.1 flowchart)."""
        exact_hit = _hit(score=1.0, match_type=MatchType.EXACT_ARTICLE)
        repo = FakeSearchRepository(exact_hits=[exact_hit])
        engine = MatchingEngine(repo)

        result = await engine.match(_input())

        # Только один вызов — exact article
        assert len(repo.calls) == 1
        method, kwargs = repo.calls[0]
        assert method == "article"
        assert kwargs["exact"] is True

        assert len(result.catalog) == 1
        assert result.catalog[0].confidence >= 0.95
        assert result.catalog[0].primary_match_type is MatchType.EXACT_ARTICLE

    async def test_no_exact_runs_fuzzy_and_lexical(self) -> None:
        fuzzy_hit = _hit(score=0.7, match_type=MatchType.FUZZY_ARTICLE)
        lex_hit = _hit(score=0.6, match_type=MatchType.LEXICAL)
        repo = FakeSearchRepository(fuzzy_hits=[fuzzy_hit], lexical_hits=[lex_hit])
        engine = MatchingEngine(repo)

        await engine.match(_input())

        # 3 вызова: exact (пусто), fuzzy, lexical
        methods = [c[0] for c in repo.calls]
        assert methods == ["article", "article", "lexical"]
        # Exact, потом fuzzy
        assert repo.calls[0][1]["exact"] is True
        assert repo.calls[1][1]["exact"] is False

    async def test_no_article_only_lexical(self) -> None:
        """input без article_normalized → ни L1, ни L2 не вызываются."""
        lex_hit = _hit(score=0.7, match_type=MatchType.LEXICAL)
        repo = FakeSearchRepository(lexical_hits=[lex_hit])
        engine = MatchingEngine(repo)

        await engine.match(_input(article_normalized=None))

        methods = [c[0] for c in repo.calls]
        assert methods == ["lexical"]

    async def test_empty_input_skips_all(self) -> None:
        repo = FakeSearchRepository()
        engine = MatchingEngine(repo)

        result = await engine.match(_input(article_normalized=None, name_normalized=None))

        assert repo.calls == []
        assert result.is_empty is True


class TestMergeAndSplit:
    async def test_same_item_merged_across_levels(self) -> None:
        same_id = uuid4()
        fuzzy_hit = _hit(item_id=same_id, score=0.8, match_type=MatchType.FUZZY_ARTICLE)
        lex_hit = _hit(item_id=same_id, score=0.7, match_type=MatchType.LEXICAL)
        repo = FakeSearchRepository(fuzzy_hits=[fuzzy_hit], lexical_hits=[lex_hit])
        engine = MatchingEngine(repo)

        result = await engine.match(_input())

        assert len(result.catalog) == 1
        cand = result.catalog[0]
        # 0.5 * 0.8 + 0.5 * 0.7 = 0.75
        assert cand.confidence == 0.75
        assert set(cand.explanation.levels_hit) == {
            MatchType.FUZZY_ARTICLE,
            MatchType.LEXICAL,
        }

    async def test_split_by_source_type(self) -> None:
        cat_hit = _hit(
            source_type=DataSourceType.COMPANY_CATALOG,
            score=0.9,
            match_type=MatchType.FUZZY_ARTICLE,
        )
        sup_hit = _hit(
            source_type=DataSourceType.SUPPLIER_PRICELIST,
            score=0.8,
            match_type=MatchType.FUZZY_ARTICLE,
        )
        repo = FakeSearchRepository(fuzzy_hits=[cat_hit, sup_hit])
        engine = MatchingEngine(repo)

        result = await engine.match(_input())

        assert len(result.catalog) == 1
        assert len(result.suppliers) == 1
        assert result.catalog[0].rank == 1
        assert result.suppliers[0].rank == 1

    async def test_top_n_truncation(self) -> None:
        hits = [
            _hit(score=score, match_type=MatchType.FUZZY_ARTICLE)
            for score in [0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6]
        ]
        repo = FakeSearchRepository(fuzzy_hits=hits)
        engine = MatchingEngine(repo)

        result = await engine.match(_input(), top_n=3)

        assert len(result.catalog) == 3
        # Отсортированы по убыванию confidence
        confidences = [c.confidence for c in result.catalog]
        assert confidences == sorted(confidences, reverse=True)
        # Ранги расставлены
        assert [c.rank for c in result.catalog] == [1, 2, 3]


class TestMatchMany:
    async def test_returns_one_result_per_input_in_order(self) -> None:
        repo = FakeSearchRepository(
            exact_hits=[_hit(score=1.0, match_type=MatchType.EXACT_ARTICLE)]
        )
        engine = MatchingEngine(repo)

        inputs = [
            _input(article_normalized="A"),
            _input(article_normalized="B"),
            _input(article_normalized="C"),
        ]
        results = await engine.match_many(inputs)
        assert len(results) == 3
