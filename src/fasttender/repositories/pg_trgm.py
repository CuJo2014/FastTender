"""SearchRepository на PostgreSQL pg_trgm + tsvector (Фаза 1, раздел 12.2).

Использует индексы, созданные в миграции 0001:
  - `ix_item_article_trgm` (partial GIN, `article_normalized IS NOT NULL`)
  - `ix_item_name_trgm` (partial GIN, `name_normalized IS NOT NULL`)
  - `ix_item_name_tsv` (GIN на generated tsvector с русским словарём)

Все SQL — через `text()` с bound params, никаких f-string-ов с входными
данными. Списочные параметры — через `bindparam(..., expanding=True)`.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import TextClause

from fasttender.models.enums import DataSourceType, MatchType
from fasttender.repositories.search import SearchHit, SearchRepository, SourceFilter

# Базовый SELECT — выбираем нужные колонки + источник для match_type/source_type
_BASE_COLUMNS = """
    item.id              AS item_id,
    item.source_id       AS source_id,
    ds.type              AS source_type,
    item.article_raw     AS article_raw,
    item.article_normalized AS article_normalized,
    item.name            AS name,
    item.name_normalized AS name_normalized,
    item.manufacturer    AS manufacturer,
    item.manufacturer_normalized AS manufacturer_normalized,
    item.price           AS price,
    item.currency        AS currency,
    item.unit            AS unit,
    item.in_stock        AS in_stock,
    item.is_active       AS is_active
"""


class PgTrgmSearchRepository(SearchRepository):
    """Реализация SearchRepository для PostgreSQL с pg_trgm и tsvector."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_by_article(
        self,
        article: str,
        *,
        exact: bool = False,
        source_filter: SourceFilter | None = None,
        limit: int = 10,
        min_similarity: float = 0.4,
    ) -> list[SearchHit]:
        if not article:
            return []

        params: dict[str, Any] = {"article": article, "limit": limit}
        filter_sql, filter_params, expanding = _filter_clause(source_filter, prefix="article")
        params.update(filter_params)

        if exact:
            sql = f"""
                SELECT
                    {_BASE_COLUMNS},
                    1.0::float AS score
                FROM item
                JOIN data_source AS ds ON ds.id = item.source_id
                WHERE item.article_normalized IS NOT NULL
                  AND item.article_normalized = :article
                  {filter_sql}
                ORDER BY ds.type, item.name
                LIMIT :limit
            """
            match_type = MatchType.EXACT_ARTICLE
        else:
            sql = f"""
                SELECT
                    {_BASE_COLUMNS},
                    similarity(item.article_normalized, :article)::float AS score
                FROM item
                JOIN data_source AS ds ON ds.id = item.source_id
                WHERE item.article_normalized IS NOT NULL
                  AND item.article_normalized % :article
                  AND similarity(item.article_normalized, :article) >= :min_sim
                  {filter_sql}
                ORDER BY score DESC, item.name
                LIMIT :limit
            """
            params["min_sim"] = min_similarity
            match_type = MatchType.FUZZY_ARTICLE

        stmt = _bind_expanding(text(sql), expanding)
        rows = (await self._session.execute(stmt, params)).mappings().all()
        return [_row_to_hit(row, match_type) for row in rows]

    async def search_lexical(
        self,
        query: str,
        *,
        source_filter: SourceFilter | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        if not query:
            return []

        params: dict[str, Any] = {"q": query, "limit": limit}
        filter_sql, filter_params, expanding = _filter_clause(source_filter, prefix="lex")
        params.update(filter_params)

        # ts_rank нормализуется как rank/(rank+1) → диапазон [0,1).
        # Trigram similarity уже в [0,1]. GREATEST даёт максимум,
        # что и считаем итоговым lexical score.
        # Используем websearch_to_tsquery — он толерантнее к коротким и
        # «человеческим» запросам, чем plainto_tsquery, и даёт OR-семантику.
        sql = f"""
            WITH q AS (
                SELECT
                    websearch_to_tsquery('russian', :q) AS tsq,
                    :q AS raw
            )
            SELECT
                {_BASE_COLUMNS},
                GREATEST(
                    COALESCE(ts_rank(item.name_tsv, q.tsq), 0) /
                        (COALESCE(ts_rank(item.name_tsv, q.tsq), 0) + 1.0),
                    COALESCE(similarity(item.name_normalized, q.raw), 0)
                )::float AS score
            FROM item
            JOIN data_source AS ds ON ds.id = item.source_id
            CROSS JOIN q
            WHERE item.name_normalized IS NOT NULL
              AND (
                  item.name_tsv @@ q.tsq
                  OR similarity(item.name_normalized, q.raw) >= 0.3
              )
              {filter_sql}
            ORDER BY score DESC, item.name
            LIMIT :limit
        """
        stmt = _bind_expanding(text(sql), expanding)
        rows = (await self._session.execute(stmt, params)).mappings().all()
        return [_row_to_hit(row, MatchType.LEXICAL) for row in rows]


# --- Внутренние утилиты ---


def _filter_clause(
    source_filter: SourceFilter | None,
    *,
    prefix: str,
) -> tuple[str, dict[str, Any], list[str]]:
    """Строит дополнительный WHERE-фрагмент и параметры из SourceFilter.

    `prefix` нужен, чтобы имена параметров не конфликтовали между
    разными вызовами в одной транзакции.
    Возвращает (sql_fragment_с_лидирующим_AND, params, expanding_param_names).
    """
    if source_filter is None:
        source_filter = SourceFilter()  # дефолтные only_active=True

    parts: list[str] = []
    params: dict[str, Any] = {}
    expanding: list[str] = []

    if source_filter.only_active:
        parts.append("item.is_active = true")
        parts.append("ds.status = 'active'")

    if source_filter.types:
        key = f"{prefix}_types"
        parts.append(f"ds.type IN :{key}")
        params[key] = tuple(t.value for t in source_filter.types)
        expanding.append(key)

    if source_filter.source_ids:
        key = f"{prefix}_source_ids"
        parts.append(f"ds.id IN :{key}")
        params[key] = tuple(source_filter.source_ids)
        expanding.append(key)

    if source_filter.supplier_ids:
        key = f"{prefix}_supplier_ids"
        parts.append(f"ds.supplier_id IN :{key}")
        params[key] = tuple(source_filter.supplier_ids)
        expanding.append(key)

    if not parts:
        return "", {}, []

    return " AND " + " AND ".join(parts), params, expanding


def _bind_expanding(stmt: TextClause, expanding: list[str]) -> TextClause:
    """Помечает указанные параметры как expanding (для IN-листов)."""
    if not expanding:
        return stmt
    binds = []
    for name in expanding:
        # Для UUID-листов используем PgUUID, для остальных — без явного типа
        type_ = PgUUID(as_uuid=True) if name.endswith("_ids") else None
        binds.append(bindparam(name, expanding=True, type_=type_))
    return stmt.bindparams(*binds)


def _row_to_hit(row: Any, match_type: MatchType) -> SearchHit:
    """Превращает строку результата в SearchHit."""
    return SearchHit(
        item_id=row["item_id"],
        source_id=row["source_id"],
        source_type=DataSourceType(row["source_type"]),
        article_raw=row["article_raw"],
        article_normalized=row["article_normalized"],
        name=row["name"],
        name_normalized=row["name_normalized"],
        manufacturer=row["manufacturer"],
        manufacturer_normalized=row["manufacturer_normalized"],
        price=Decimal(row["price"]) if row["price"] is not None else None,
        currency=row["currency"],
        unit=row["unit"],
        in_stock=bool(row["in_stock"]),
        is_active=bool(row["is_active"]),
        score=float(row["score"]),
        match_type=match_type,
    )


# Re-export для удобства
__all__ = ["PgTrgmSearchRepository"]


# Защита от случайного использования UUID без импорта
_ = UUID
