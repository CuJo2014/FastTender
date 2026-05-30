"""DTO для API спецификаций (Приложение C.4)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from fasttender.models.enums import (
    DataSourceType,
    MatchType,
    SpecificationStatus,
    VerificationDecision,
)


class SpecificationCounts(BaseModel):
    """Агрегаты по спецификации (отображаются в списке/детали)."""

    items_total: int = 0
    items_matched_high: int = 0  # confidence >= auto_confirm threshold
    items_matched_medium: int = 0  # min <= confidence < auto_confirm
    items_not_found: int = 0  # confidence < min или нет кандидатов


class SpecificationRead(BaseModel):
    """Общая информация о спецификации (GET / и GET /{id})."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_filename: str
    client_name: str | None
    status: SpecificationStatus
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    counts: SpecificationCounts = Field(default_factory=SpecificationCounts)


class SpecificationUploadResponse(BaseModel):
    """Ответ POST /specifications/ (202 Accepted)."""

    spec_id: UUID
    status: SpecificationStatus
    filename: str
    created_at: datetime


class LinkedCatalogItemRead(BaseModel):
    """Снимок каталог-карточки, к которой привязана прайс-позиция (миграция 0008)."""

    item_id: UUID
    code_1c: str | None = None
    article: str | None = None
    name: str
    manufacturer: str | None = None


class CandidateRead(BaseModel):
    """Один кандидат для отображения в UI (источник из item.source.type)."""

    item_id: UUID
    source_id: UUID
    source_type: DataSourceType

    article: str | None = None
    code_1c: str | None = None  # внутренний код 1С — стабильный идентификатор
    supplier_sku: str | None = None  # внутренний SKU прайса поставщика, <prefix>-<NNNNNN>
    name: str
    manufacturer: str | None = None
    category_path: str | None = None  # «Крепёж / Болты / DIN933» из 1С
    price: Decimal | None = None
    currency: str | None = None
    unit: str | None = None
    in_stock: bool = True

    # Связь с карточкой каталога (для позиций из прайсов поставщиков).
    # auto = определено импортером, manual = выбор менеджера.
    linked_catalog: LinkedCatalogItemRead | None = None
    catalog_link_source: str | None = None  # 'auto' | 'manual' | None

    confidence: float
    match_type: MatchType
    rank: int
    explanation: dict[str, Any]


class VerificationRead(BaseModel):
    """Решение менеджера по строке."""

    decision: VerificationDecision
    chosen_item_id: UUID | None = None
    decided_by: str | None = None
    notes: str | None = None
    decided_at: datetime


class SpecItemRead(BaseModel):
    """Строка спецификации со снимком raw+normalized и кандидатами."""

    id: UUID
    line_number: int

    name_raw: str
    article_raw: str | None
    manufacturer_raw: str | None
    unit_raw: str | None
    quantity: Decimal | None
    price_raw: Decimal | None
    currency_raw: str | None
    notes: str | None

    name_normalized: str | None
    article_normalized: str | None
    unit_normalized: str | None

    candidates_catalog: list[CandidateRead] = Field(default_factory=list)
    candidates_suppliers: list[CandidateRead] = Field(default_factory=list)
    verification: VerificationRead | None = None


class PaginatedSpecItems(BaseModel):
    items: list[SpecItemRead]
    total: int
    page: int
    page_size: int
