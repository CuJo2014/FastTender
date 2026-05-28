"""Гибридная пересортировка кандидатов (раздел 9.2).

Чистые функции — никакого I/O. Тестируются юнит-тестами без БД.

Формула (раздел 9.2):
    final_score =
        w_article × article_similarity +
        w_lexical × bm25_score +
        w_semantic × cosine_similarity +    # 0 в Фазе 1
        boost_brand × brand_match +
        boost_unit × unit_match +
        boost_attrs × attributes_match      # 0 в Фазе 1

В Фазе 1 семантического и атрибутивного слоёв нет, поэтому формула
сводится к w_article × art_sim + w_lexical × lex + бустам.

Особый случай — точное совпадение по нормализованному артикулу:
вместо взвешенной суммы выставляется baseline 0.95 + небольшие
бусты за бренд/единицу. Доп. бусты поверх weighted sum, когда score
уже ≥ 0.95, не применяются — они бы силенциально терялись из-за
капа на 1.0 и портили бы explanation.
"""

from dataclasses import dataclass, field

from fasttender.models.enums import MatchType
from fasttender.repositories.search import SearchHit
from fasttender.services.matcher.types import Candidate, Explanation, MatchInput


@dataclass(frozen=True)
class Weights:
    """Веса гибридного re-ranking'а.

    Дефолты — стартовые экспертные значения (раздел 9.2). Подстраиваются
    на золотом датасете в Фазе 2 (раздел 9.5).
    """

    w_article: float = 0.5
    w_lexical: float = 0.5
    boost_brand: float = 0.10
    boost_unit: float = 0.05

    # Особый случай exact-article — отдельный baseline + маленькие бусты
    exact_article_baseline: float = 0.95
    exact_article_brand_bump: float = 0.03
    exact_article_unit_bump: float = 0.02


@dataclass
class AggregatedHit:
    """Один Item, найденный одним или несколькими уровнями матчера.

    Хранит per-level сырые оценки, чтобы re-ranker мог применить формулу,
    и снимок данных Item для финального Candidate.
    """

    hit: SearchHit  # «канонический» снимок (берём из первого уровня)
    article_exact: float = 0.0  # 1.0 если был exact-hit, иначе 0
    article_fuzzy: float = 0.0  # similarity для fuzzy-hit
    lexical: float = 0.0  # нормализованный score из search_lexical
    levels_hit: list[MatchType] = field(default_factory=list)


def merge_hits(per_level: dict[MatchType, list[SearchHit]]) -> list[AggregatedHit]:
    """Дедупликация пула кандидатов по item_id.

    Каждый item сохраняет лучшие оценки с каждого уровня (если
    встречается несколько раз). Multi-level boost в Фазе 1 не вводим —
    только запоминаем `levels_hit` для прозрачности (см. план).
    """
    by_item: dict[str, AggregatedHit] = {}

    for match_type, hits in per_level.items():
        for hit in hits:
            key = str(hit.item_id)
            agg = by_item.get(key)
            if agg is None:
                agg = AggregatedHit(hit=hit, levels_hit=[match_type])
                by_item[key] = agg
            else:
                if match_type not in agg.levels_hit:
                    agg.levels_hit.append(match_type)
                # При коллизии — оставляем более «полный» снимок
                # (с непустыми manufacturer_normalized и т.п.).
                if agg.hit.manufacturer_normalized is None and hit.manufacturer_normalized:
                    agg.hit = hit

            if match_type is MatchType.EXACT_ARTICLE:
                agg.article_exact = max(agg.article_exact, hit.score)
            elif match_type is MatchType.FUZZY_ARTICLE:
                agg.article_fuzzy = max(agg.article_fuzzy, hit.score)
            elif match_type is MatchType.LEXICAL:
                agg.lexical = max(agg.lexical, hit.score)

    return list(by_item.values())


def _brand_match(input_: MatchInput, hit: SearchHit) -> bool:
    """Case-insensitive equality нормализованных производителей."""
    if not input_.manufacturer_normalized or not hit.manufacturer_normalized:
        return False
    return input_.manufacturer_normalized.lower() == hit.manufacturer_normalized.lower()


def _unit_match(input_: MatchInput, hit: SearchHit) -> bool:
    """Equality нормализованных единиц измерения.

    В Фазе 1 — точное равенство; в Фазе 2 здесь будет словарь синонимов
    («шт» = «pcs» = «штук», раздел 10.3).
    """
    if not input_.unit_normalized or not hit.unit:
        return False
    return input_.unit_normalized.strip().lower() == hit.unit.strip().lower()


def score_candidate(
    input_: MatchInput,
    agg: AggregatedHit,
    weights: Weights,
    rank: int = 0,
) -> Candidate:
    """Применяет формулу и собирает финальный Candidate.

    rank по умолчанию 0 (= не присвоен); вызывающий код после сортировки
    выставляет реальный rank через `model_copy`.
    """
    brand = _brand_match(input_, agg.hit)
    unit = _unit_match(input_, agg.hit)

    if agg.article_exact >= 1.0:
        # Уровень 1 короткозамкнул — отдельный baseline (раздел 9.1)
        final = weights.exact_article_baseline
        if brand:
            final += weights.exact_article_brand_bump
        if unit:
            final += weights.exact_article_unit_bump
        article_match = "exact_after_normalization"
        article_similarity = 1.0
        primary = MatchType.EXACT_ARTICLE
    else:
        # Уровни 2 + 3 — взвешенная сумма + бусты
        article_similarity = agg.article_fuzzy
        weighted = weights.w_article * article_similarity + weights.w_lexical * agg.lexical
        bonuses = (weights.boost_brand if brand else 0.0) + (weights.boost_unit if unit else 0.0)
        final = weighted + bonuses
        if article_similarity > 0:
            article_match = "fuzzy"
            primary = (
                MatchType.FUZZY_ARTICLE if article_similarity >= agg.lexical else MatchType.LEXICAL
            )
        else:
            article_match = "none"
            primary = MatchType.LEXICAL

    final = max(0.0, min(1.0, final))

    explanation = Explanation(
        article_match=article_match,
        article_similarity=article_similarity,
        lexical_score=agg.lexical,
        semantic_similarity=0.0,
        brand_match=brand,
        unit_match=unit,
        final_score=final,
        human_readable="",  # заполним ниже
        levels_hit=list(agg.levels_hit),
    )
    explanation.human_readable = human_readable_explanation(explanation)

    return Candidate(
        item_id=agg.hit.item_id,
        source_id=agg.hit.source_id,
        source_type=agg.hit.source_type,
        article=agg.hit.article_raw,
        name=agg.hit.name,
        manufacturer=agg.hit.manufacturer,
        price=agg.hit.price,
        currency=agg.hit.currency,
        unit=agg.hit.unit,
        confidence=final,
        primary_match_type=primary,
        explanation=explanation,
        rank=rank,
    )


def human_readable_explanation(explanation: Explanation) -> str:
    """Краткое русскоязычное описание для UI (раздел 9.3)."""
    parts: list[str] = []

    if explanation.article_match == "exact_after_normalization":
        parts.append("артикул совпал точно")
    elif explanation.article_match == "fuzzy":
        parts.append(f"артикул похож (similarity={explanation.article_similarity:.2f})")

    if explanation.lexical_score > 0:
        parts.append(f"наименование близко (score={explanation.lexical_score:.2f})")

    if explanation.brand_match:
        parts.append("совпал бренд")
    if explanation.unit_match:
        parts.append("совпала единица измерения")

    if not parts:
        return "слабое совпадение"

    sentence = ", ".join(parts)
    return sentence[0].upper() + sentence[1:]
