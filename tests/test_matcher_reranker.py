"""Unit-тесты гибридного re-ranker'а матчера (раздел 9.2)."""

from decimal import Decimal
from uuid import uuid4

import pytest

from fasttender.models.enums import DataSourceType, MatchType
from fasttender.repositories.search import SearchHit
from fasttender.services.matcher.reranker import (
    AggregatedHit,
    Weights,
    human_readable_explanation,
    merge_hits,
    score_candidate,
)
from fasttender.services.matcher.types import Explanation, MatchInput


def _hit(
    *,
    item_id=None,
    manufacturer_normalized: str | None = None,
    unit: str | None = None,
    name: str = "Болт М10",
    source_type: DataSourceType = DataSourceType.COMPANY_CATALOG,
    score: float = 0.0,
    match_type: MatchType = MatchType.EXACT_ARTICLE,
) -> SearchHit:
    return SearchHit(
        item_id=item_id or uuid4(),
        source_id=uuid4(),
        source_type=source_type,
        article_raw="BLT-001",
        article_normalized="BLT001",
        name=name,
        name_normalized=name.lower(),
        manufacturer="KOELNER" if manufacturer_normalized else None,
        manufacturer_normalized=manufacturer_normalized,
        price=Decimal("10"),
        currency="RUB",
        unit=unit,
        score=score,
        match_type=match_type,
    )


def _input(
    *,
    article_normalized: str | None = "BLT001",
    manufacturer_normalized: str | None = None,
    unit_normalized: str | None = None,
) -> MatchInput:
    return MatchInput(
        line_number=1,
        name="Болт",
        name_normalized="болт",
        article="BLT-001",
        article_normalized=article_normalized,
        manufacturer="KOELNER" if manufacturer_normalized else None,
        manufacturer_normalized=manufacturer_normalized,
        unit="шт",
        unit_normalized=unit_normalized,
    )


# --- merge_hits ---


class TestMergeHits:
    def test_single_level_single_hit(self) -> None:
        h = _hit(score=0.8, match_type=MatchType.FUZZY_ARTICLE)
        result = merge_hits({MatchType.FUZZY_ARTICLE: [h]})
        assert len(result) == 1
        assert result[0].article_fuzzy == 0.8
        assert result[0].levels_hit == [MatchType.FUZZY_ARTICLE]

    def test_same_item_multiple_levels(self) -> None:
        same_id = uuid4()
        h1 = _hit(item_id=same_id, score=0.8, match_type=MatchType.FUZZY_ARTICLE)
        h2 = _hit(item_id=same_id, score=0.7, match_type=MatchType.LEXICAL)
        result = merge_hits({MatchType.FUZZY_ARTICLE: [h1], MatchType.LEXICAL: [h2]})
        assert len(result) == 1
        agg = result[0]
        assert agg.article_fuzzy == 0.8
        assert agg.lexical == 0.7
        assert set(agg.levels_hit) == {MatchType.FUZZY_ARTICLE, MatchType.LEXICAL}

    def test_different_items_stay_separate(self) -> None:
        h1 = _hit(score=0.9, match_type=MatchType.EXACT_ARTICLE)
        h2 = _hit(score=0.5, match_type=MatchType.EXACT_ARTICLE)
        result = merge_hits({MatchType.EXACT_ARTICLE: [h1, h2]})
        assert len(result) == 2


# --- score_candidate ---


class TestScoreCandidateFormula:
    def test_only_fuzzy_article(self) -> None:
        agg = AggregatedHit(
            hit=_hit(score=0.8, match_type=MatchType.FUZZY_ARTICLE),
            article_fuzzy=0.8,
            levels_hit=[MatchType.FUZZY_ARTICLE],
        )
        cand = score_candidate(_input(), agg, Weights(), rank=1)
        # final = 0.5 * 0.8 + 0.5 * 0 = 0.4
        assert cand.confidence == pytest.approx(0.4)
        assert cand.primary_match_type is MatchType.FUZZY_ARTICLE

    def test_only_lexical(self) -> None:
        agg = AggregatedHit(
            hit=_hit(score=0.7, match_type=MatchType.LEXICAL),
            lexical=0.7,
            levels_hit=[MatchType.LEXICAL],
        )
        cand = score_candidate(_input(article_normalized=None), agg, Weights(), rank=1)
        # final = 0.5*0 + 0.5*0.7 = 0.35
        assert cand.confidence == pytest.approx(0.35)
        assert cand.primary_match_type is MatchType.LEXICAL

    def test_fuzzy_and_lexical_combined(self) -> None:
        agg = AggregatedHit(
            hit=_hit(score=0, match_type=MatchType.FUZZY_ARTICLE),
            article_fuzzy=0.8,
            lexical=0.7,
            levels_hit=[MatchType.FUZZY_ARTICLE, MatchType.LEXICAL],
        )
        cand = score_candidate(_input(), agg, Weights(), rank=1)
        # 0.5 * 0.8 + 0.5 * 0.7 = 0.75
        assert cand.confidence == pytest.approx(0.75)

    def test_brand_boost_only_when_normalized_brands_match(self) -> None:
        agg = AggregatedHit(
            hit=_hit(score=0.8, manufacturer_normalized="koelner"),
            article_fuzzy=0.8,
            levels_hit=[MatchType.FUZZY_ARTICLE],
        )
        cand = score_candidate(_input(manufacturer_normalized="koelner"), agg, Weights(), rank=1)
        # 0.5 * 0.8 + 0.5 * 0 + 0.1 = 0.5
        assert cand.confidence == pytest.approx(0.5)
        assert cand.explanation.brand_match is True

    def test_brand_no_boost_when_brand_missing_in_hit(self) -> None:
        agg = AggregatedHit(
            hit=_hit(score=0.8, manufacturer_normalized=None),
            article_fuzzy=0.8,
            levels_hit=[MatchType.FUZZY_ARTICLE],
        )
        cand = score_candidate(_input(manufacturer_normalized="koelner"), agg, Weights(), rank=1)
        assert cand.explanation.brand_match is False
        assert cand.confidence == pytest.approx(0.4)

    def test_unit_boost(self) -> None:
        agg = AggregatedHit(
            hit=_hit(score=0.8, unit="шт"),
            article_fuzzy=0.8,
            levels_hit=[MatchType.FUZZY_ARTICLE],
        )
        cand = score_candidate(_input(unit_normalized="шт"), agg, Weights(), rank=1)
        # 0.4 + 0.05 = 0.45
        assert cand.confidence == pytest.approx(0.45)
        assert cand.explanation.unit_match is True

    def test_final_score_capped_at_1(self) -> None:
        agg = AggregatedHit(
            hit=_hit(score=1.0, manufacturer_normalized="koelner", unit="шт"),
            article_fuzzy=1.0,
            lexical=1.0,
            levels_hit=[MatchType.FUZZY_ARTICLE, MatchType.LEXICAL],
        )
        cand = score_candidate(
            _input(manufacturer_normalized="koelner", unit_normalized="шт"),
            agg,
            Weights(),
            rank=1,
        )
        # 0.5 + 0.5 + 0.1 + 0.05 = 1.15 → cap 1.0
        assert cand.confidence == 1.0


class TestExactArticleFastPath:
    def test_exact_article_baseline(self) -> None:
        agg = AggregatedHit(
            hit=_hit(score=1.0, match_type=MatchType.EXACT_ARTICLE),
            article_exact=1.0,
            levels_hit=[MatchType.EXACT_ARTICLE],
        )
        cand = score_candidate(_input(), agg, Weights(), rank=1)
        assert cand.confidence == pytest.approx(0.95)
        assert cand.primary_match_type is MatchType.EXACT_ARTICLE
        assert cand.explanation.article_match == "exact_after_normalization"

    def test_exact_with_brand_bump(self) -> None:
        agg = AggregatedHit(
            hit=_hit(
                score=1.0,
                match_type=MatchType.EXACT_ARTICLE,
                manufacturer_normalized="koelner",
            ),
            article_exact=1.0,
            levels_hit=[MatchType.EXACT_ARTICLE],
        )
        cand = score_candidate(_input(manufacturer_normalized="koelner"), agg, Weights(), rank=1)
        assert cand.confidence == pytest.approx(0.98)

    def test_exact_with_brand_and_unit_bumps_capped(self) -> None:
        agg = AggregatedHit(
            hit=_hit(
                score=1.0,
                match_type=MatchType.EXACT_ARTICLE,
                manufacturer_normalized="koelner",
                unit="шт",
            ),
            article_exact=1.0,
            levels_hit=[MatchType.EXACT_ARTICLE],
        )
        cand = score_candidate(
            _input(manufacturer_normalized="koelner", unit_normalized="шт"),
            agg,
            Weights(),
            rank=1,
        )
        # 0.95 + 0.03 + 0.02 = 1.0
        assert cand.confidence == pytest.approx(1.0)


class TestCustomWeights:
    def test_increased_article_weight(self) -> None:
        agg = AggregatedHit(
            hit=_hit(score=0.8, match_type=MatchType.FUZZY_ARTICLE),
            article_fuzzy=0.8,
            lexical=0.4,
            levels_hit=[MatchType.FUZZY_ARTICLE, MatchType.LEXICAL],
        )
        weights = Weights(w_article=0.8, w_lexical=0.2)
        cand = score_candidate(_input(), agg, weights, rank=1)
        # 0.8 * 0.8 + 0.2 * 0.4 = 0.72
        assert cand.confidence == pytest.approx(0.72)


class TestHumanReadable:
    def test_exact_article_phrase(self) -> None:
        explanation = Explanation(
            article_match="exact_after_normalization",
            article_similarity=1.0,
            lexical_score=0.0,
            brand_match=True,
            unit_match=True,
            final_score=1.0,
            human_readable="",
        )
        text = human_readable_explanation(explanation)
        assert "точно" in text
        assert "бренд" in text
        assert "единица" in text

    def test_fuzzy_phrase(self) -> None:
        explanation = Explanation(
            article_match="fuzzy",
            article_similarity=0.85,
            lexical_score=0.6,
            final_score=0.72,
            human_readable="",
        )
        text = human_readable_explanation(explanation)
        assert "похож" in text
        assert "наименование" in text

    def test_weak_match(self) -> None:
        explanation = Explanation(
            article_match="none",
            article_similarity=0.0,
            lexical_score=0.0,
            final_score=0.1,
            human_readable="",
        )
        text = human_readable_explanation(explanation)
        assert text == "слабое совпадение"
