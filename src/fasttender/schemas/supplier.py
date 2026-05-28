"""DTO для поставщиков и их прайсов."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from fasttender.models.enums import DataSourceStatus


class SupplierCreate(BaseModel):
    """Тело POST /suppliers."""

    name: str = Field(..., min_length=1, max_length=255)
    contact_email: EmailStr | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SupplierRead(BaseModel):
    """Ответ GET /suppliers и GET /suppliers/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    contact_email: str | None
    meta: dict[str, Any]
    created_at: datetime


class PricelistSourceRead(BaseModel):
    """Информация о DataSource типа SUPPLIER_PRICELIST для поставщика."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    supplier_id: UUID
    status: DataSourceStatus
    config: dict[str, Any]
    last_synced_at: datetime | None
    created_at: datetime
