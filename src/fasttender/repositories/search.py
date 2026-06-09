"""SearchRepository Protocol и его доменные типы (раздел 12.6).

Этот интерфейс — точка переключения поискового движка между Фазой 1
(`PgTrgmSearchRepository`) и Фазой 2 (`OpenSearchRepository`,
`PgVectorRepository`, гибрид). Бизнес-логика матчера зависит только
от Protocol — не от конкретной реализации.

Имена методов фиксированы документом (раздел 12.6):
search_by_article, search_lexical, search_semantic, search_hybrid.
"""

from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from fasttender.models.enums import DataSourceType, MatchType


class SourceFilter(BaseModel):
    """Фильтр источников для поиска.

    None в каждом из списков означает «без ограничений по этому измерению».
    `only_active=True` отсекает деактивированные позиции (item.is_active=false)
    **и** деактивированные источники (data_source.status != 'active') —
    эти два флага независимы, репозиторий обязан учитывать оба.
    """

    model_config = ConfigDict(frozen=True)

    types: tuple[DataSourceType, ...] | None = None
    source_ids: tuple[UUID, ...] | None = None
    supplier_ids: tuple[UUID, ...] | None = None
    only_active: bool = True


class SearchHit(BaseModel):
    """Снимок строки Item с сырой оценкой поиска.

    Поля закрывают всё, что нужно UI для отображения кандидата, плюс
    `score` (специфичный для движка: similarity, ts_rank, cosine, ...)
    и `match_type` — каким уровнем матчинга найдено.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    item_id: UUID
    source_id: UUID
    source_type: DataSourceType

    article_raw: str | None = None
    article_normalized: str | None = None
    code_1c: str | None = None
    name: str
    name_normalized: str | None = None
    manufacturer: str | None = None
    manufacturer_normalized: str | None = None

    price: Decimal | None = None
    currency: str | None = None
    unit: str | None = None
    in_stock: bool = True
    is_active: bool = True

    score: float = Field(..., ge=0.0)
    match_type: MatchType


@runtime_checkable
class SearchRepository(Protocol):
    """Абстракция поиска по индексу Item (раздел 12.6 архитектуры).

    Реализации:
      - `PgTrgmSearchRepository` (Фаза 1) — PostgreSQL pg_trgm + tsvector.
      - `OpenSearchRepository` (Фаза 2) — BM25, морфология.
      - `PgVectorRepository` / `QdrantRepository` (Фаза 2) — семантика.
      - Гибрид (Фаза 2) — `search_hybrid` поверх первых двух.

    Все методы async, чтобы единообразно работать с любыми backend'ами.
    """

    async def search_by_article(
        self,
        article: str,
        *,
        exact: bool = False,
        source_filter: SourceFilter | None = None,
        limit: int = 10,
        min_similarity: float = 0.4,
    ) -> list[SearchHit]:
        """Поиск по нормализованному артикулу.

        `exact=True` — только точное совпадение (для уровня 1 матчера),
        score=1.0 у всех попавших.
        `exact=False` — нечёткий поиск (уровень 2), score=similarity.
        `min_similarity` применяется только при `exact=False`.
        """
        ...

    async def search_lexical(
        self,
        query: str,
        *,
        source_filter: SourceFilter | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Полнотекстовый+нечёткий поиск по наименованию (уровень 3 матчера).

        Реализация Фазы 1 комбинирует tsvector (`name_tsv @@ tsquery`)
        с trigram similarity на `name_normalized`. Score — в диапазоне [0,1].
        """
        ...

    async def search_by_code_in_name(
        self,
        code: str,
        *,
        source_filter: SourceFilter | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Поиск кода/модели как ПОДСТРОКИ в наименовании (`name_normalized`).

        Нужен, когда модель зашита в имя каталога, а поле `Артикул` пустое
        (частый дефект данных 1С: «Домкрат гидравлический ДГ15-3913010-03»).
        Совпавшие получают score=1.0 (наличие кода в имени — сильный сигнал).
        """
        ...

    async def known_manufacturers(
        self,
        *,
        source_filter: SourceFilter | None = None,
    ) -> set[str]:
        """Множество нормализованных производителей из индекса.

        Используется матчером, чтобы распознать бренд, зашитый в текст
        характеристик/наименования (когда отдельной колонки бренда нет).
        """
        ...

    async def search_semantic(
        self,
        embedding: list[float],
        *,
        source_filter: SourceFilter | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Семантический поиск по эмбеддингу (Фаза 2)."""
        raise NotImplementedError("Семантический поиск — Фаза 2 (раздел 12.4)")

    async def search_hybrid(
        self,
        query: str,
        *,
        embedding: list[float] | None = None,
        source_filter: SourceFilter | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Гибридный поиск (Фаза 2): лексика + семантика в одном запросе."""
        raise NotImplementedError("Гибридный поиск — Фаза 2 (раздел 12.6)")
