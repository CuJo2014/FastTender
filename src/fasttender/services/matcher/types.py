"""Доменные типы матчера (раздел 9.3).

ВАЖНО: этот модуль НЕ импортирует ORM-модели (SpecItem, Item) —
адаптеры лежат в `adapters.py`, чтобы Celery-задача, дёргающая и
матчер, и ORM, не словила import cycle.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from fasttender.models.enums import DataSourceType, MatchType


class MatchInput(BaseModel):
    """Входная позиция для матчинга (соответствует одной строке спецификации).

    Все «искомые» поля — уже нормализованные. Сырые оставлены только
    для отображения в explanation / UI и не участвуют в поиске.
    """

    model_config = ConfigDict(frozen=True)

    line_number: int = Field(..., ge=1)
    name: str
    name_normalized: str | None = None

    article: str | None = None
    article_normalized: str | None = None

    # Коды/модели, извлечённые из наименования, когда явной колонки артикула
    # нет (раздел 9.1, point 2). Матчер пробует их по article каталога.
    article_candidates: tuple[str, ...] = ()

    # Длинные цифровые серии (≥5) из наименования+характеристик — матчер ищет
    # их как ПОДСТРОКУ в наименовании каталога (модель зашита в имя, не в
    # артикул). См. extract_code_tokens.
    code_tokens: tuple[str, ...] = ()

    manufacturer: str | None = None
    manufacturer_normalized: str | None = None

    unit: str | None = None
    unit_normalized: str | None = None


class Explanation(BaseModel):
    """JSON-объяснение оценки (раздел 9.3).

    Отображается в UI при наведении на confidence. Поле
    `semantic_similarity` всегда 0 в Фазе 1 — заложено на Фазу 2.
    """

    article_match: str = "none"  # none | exact_after_normalization | fuzzy | extracted_code
    article_similarity: float = 0.0
    lexical_score: float = 0.0
    semantic_similarity: float = 0.0
    brand_match: bool = False
    unit_match: bool = False
    # Код, извлечённый из наименования и совпавший с article каталога (point 2).
    extracted_code_match: str = "none"  # none | exact | in_name | fuzzy
    extracted_code: str | None = None
    # Провенанс: карточка каталога подтянута через связанную позицию прайса
    # (Item.linked_catalog_item_id), а не найдена независимым поиском.
    linked_via_supplier: bool = False
    final_score: float
    human_readable: str
    levels_hit: list[MatchType] = Field(default_factory=list)


class Candidate(BaseModel):
    """Один кандидат в результате матчинга.

    Все поля для отображения в UI идут отсюда — фронт не лезет в Item
    отдельным запросом.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    item_id: UUID
    source_id: UUID
    source_type: DataSourceType

    article: str | None = None  # article_raw для UI
    code_1c: str | None = None
    name: str
    manufacturer: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    unit: str | None = None

    confidence: float = Field(..., ge=0.0, le=1.0)
    primary_match_type: MatchType
    explanation: Explanation
    rank: int = Field(default=0, ge=0, description="0 = ранг не присвоен (до сортировки)")


class MatchResult(BaseModel):
    """Результат матчинга одной строки спецификации (раздел 4.5)."""

    spec_item_line: int
    catalog: list[Candidate] = Field(default_factory=list)
    suppliers: list[Candidate] = Field(default_factory=list)
    searched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_empty(self) -> bool:
        return not self.catalog and not self.suppliers

    @property
    def top_catalog_confidence(self) -> float:
        return self.catalog[0].confidence if self.catalog else 0.0

    @property
    def top_supplier_confidence(self) -> float:
        return self.suppliers[0].confidence if self.suppliers else 0.0
