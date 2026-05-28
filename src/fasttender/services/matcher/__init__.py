"""Matching Engine — ядро системы (раздел 9).

Каскад уровней (раздел 9.1):
    1. Точное совпадение по артикулу — short-circuit, confidence ≥ 0.95
    2. Нечёткое по артикулу (pg_trgm similarity)
    3. Лексический поиск по наименованию (tsvector + trigram)

Уровни 4 (семантика) и 5 (LLM) — Фаза 2.

Использование:

    from fasttender.repositories.pg_trgm import PgTrgmSearchRepository
    from fasttender.services.matcher import MatchingEngine
    from fasttender.services.matcher.types import MatchInput

    repo = PgTrgmSearchRepository(session)
    engine = MatchingEngine(repo)
    result = await engine.match(MatchInput(...))
    for c in result.catalog:
        print(c.confidence, c.primary_match_type, c.name)
"""

from fasttender.models.enums import DataSourceType, MatchType
from fasttender.repositories.search import SearchHit, SearchRepository, SourceFilter
from fasttender.services.matcher.reranker import (
    AggregatedHit,
    Weights,
    merge_hits,
    score_candidate,
)
from fasttender.services.matcher.types import (
    Candidate,
    Explanation,
    MatchInput,
    MatchResult,
)

__all__ = [
    "AggregatedHit",
    "Candidate",
    "Explanation",
    "MatchInput",
    "MatchResult",
    "MatchingEngine",
    "Weights",
]


class MatchingEngine:
    """Оркестратор многоуровневого матчинга (раздел 9)."""

    def __init__(
        self,
        search_repo: SearchRepository,
        weights: Weights | None = None,
    ) -> None:
        self._repo = search_repo
        self._weights = weights or Weights()

    async def match(
        self,
        input_: MatchInput,
        *,
        top_n: int = 5,
        pool_limit: int = 20,
        source_filter: SourceFilter | None = None,
    ) -> MatchResult:
        """Матчинг одной строки спецификации.

        Алгоритм:
          1. Если есть article_normalized — запрос точного совпадения.
             Если хотя бы один hit найден — short-circuit (раздел 9.1
             flowchart: L1 hit → HIGH_CONF → TOP5, минуя L2/L3).
          2. Иначе — собрать кандидатов с L2 (fuzzy article) и L3
             (lexical name), пропустить через re-ranker.
          3. Разделить по source_type, взять top_n каталог + top_n прайсы.

        Возвращает пустой MatchResult, если в input'е нет ни артикула,
        ни name_normalized (нечего искать).
        """
        if not input_.article_normalized and not input_.name_normalized:
            return MatchResult(spec_item_line=input_.line_number)

        per_level: dict[MatchType, list[SearchHit]] = {}

        # --- Уровень 1: точное совпадение по артикулу ---
        if input_.article_normalized:
            exact_hits = await self._repo.search_by_article(
                input_.article_normalized,
                exact=True,
                source_filter=source_filter,
                limit=pool_limit,
            )
            if exact_hits:
                per_level[MatchType.EXACT_ARTICLE] = exact_hits
                return self._assemble_result(input_, per_level, top_n=top_n)

        # --- Уровень 2: нечёткое по артикулу ---
        if input_.article_normalized:
            fuzzy_hits = await self._repo.search_by_article(
                input_.article_normalized,
                exact=False,
                source_filter=source_filter,
                limit=pool_limit,
            )
            if fuzzy_hits:
                per_level[MatchType.FUZZY_ARTICLE] = fuzzy_hits

        # --- Уровень 3: лексический по наименованию ---
        if input_.name_normalized:
            lex_hits = await self._repo.search_lexical(
                input_.name_normalized,
                source_filter=source_filter,
                limit=pool_limit,
            )
            if lex_hits:
                per_level[MatchType.LEXICAL] = lex_hits

        return self._assemble_result(input_, per_level, top_n=top_n)

    async def match_many(
        self,
        inputs: list[MatchInput],
        *,
        top_n: int = 5,
        pool_limit: int = 20,
        source_filter: SourceFilter | None = None,
    ) -> list[MatchResult]:
        """Матчинг пачки строк (последовательно).

        В Фазе 1 — тонкий цикл. В Фазе 2 при batched-эмбеддингах сигнатура
        не поменяется, появится только эффективная реализация внутри.
        """
        return [
            await self.match(i, top_n=top_n, pool_limit=pool_limit, source_filter=source_filter)
            for i in inputs
        ]

    # --- Внутреннее ---

    def _assemble_result(
        self,
        input_: MatchInput,
        per_level: dict[MatchType, list[SearchHit]],
        *,
        top_n: int,
    ) -> MatchResult:
        if not per_level:
            return MatchResult(spec_item_line=input_.line_number)

        aggregated = merge_hits(per_level)
        scored = [score_candidate(input_, agg, self._weights) for agg in aggregated]
        scored.sort(key=lambda c: c.confidence, reverse=True)

        catalog = [c for c in scored if c.source_type is DataSourceType.COMPANY_CATALOG][:top_n]
        suppliers = [c for c in scored if c.source_type is DataSourceType.SUPPLIER_PRICELIST][
            :top_n
        ]

        # Заполняем rank внутри каждой группы
        for idx, cand in enumerate(catalog, start=1):
            catalog[idx - 1] = cand.model_copy(update={"rank": idx})
        for idx, cand in enumerate(suppliers, start=1):
            suppliers[idx - 1] = cand.model_copy(update={"rank": idx})

        return MatchResult(
            spec_item_line=input_.line_number,
            catalog=catalog,
            suppliers=suppliers,
        )
