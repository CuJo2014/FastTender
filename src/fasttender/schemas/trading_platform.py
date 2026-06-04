"""DTO справочника торговых площадок (ЭТП)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TradingPlatformCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    url: str | None = Field(None, max_length=512)
    notes: str | None = Field(None, max_length=2048)
    meta: dict[str, Any] = Field(default_factory=dict)


class TradingPlatformUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    url: str | None = Field(None, max_length=512)
    notes: str | None = Field(None, max_length=2048)
    meta: dict[str, Any] | None = None


class TradingPlatformRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str | None
    notes: str | None
    meta: dict[str, Any]
    created_at: datetime
    specifications_count: int = 0
