"""DTO справочника клиентов."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClientCreate(BaseModel):
    """Тело POST /clients."""

    name: str = Field(..., min_length=1, max_length=255)
    inn: str | None = Field(None, max_length=32)
    contact: str | None = Field(None, max_length=512)
    notes: str | None = Field(None, max_length=2048)
    meta: dict[str, Any] = Field(default_factory=dict)


class ClientUpdate(BaseModel):
    """Тело PATCH /clients/{id} — все поля опциональны."""

    name: str | None = Field(None, min_length=1, max_length=255)
    inn: str | None = Field(None, max_length=32)
    contact: str | None = Field(None, max_length=512)
    notes: str | None = Field(None, max_length=2048)
    meta: dict[str, Any] | None = None


class ClientRead(BaseModel):
    """Ответ GET /clients и GET /clients/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    inn: str | None
    contact: str | None
    notes: str | None
    meta: dict[str, Any]
    created_at: datetime
    # Сколько спецификаций ссылается на клиента (для UI и защиты при удалении)
    specifications_count: int = 0
