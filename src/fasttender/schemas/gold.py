"""DTO золотого датасета (раздел 15.4, 16.3)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from fasttender.models.enums import GoldLabelStatus


class GoldRowCreate(BaseModel):
    """Тело POST /gold-rows — ручное создание строки эталона."""

    # Исходные данные (как у клиента)
    source_file: str | None = Field(None, max_length=512)
    name: str = Field(..., min_length=1, max_length=1024)
    article: str | None = Field(None, max_length=255)
    manufacturer: str | None = Field(None, max_length=255)
    attributes: str | None = Field(None, max_length=2048)
    quantity: float | None = None
    unit: str | None = Field(None, max_length=64)

    # Эталонная разметка. Если задан expected_item_id, пустые expected_*
    # допустимо не указывать — бэкенд снимет снимок из позиции каталога.
    expected_article: str | None = Field(None, max_length=255)
    expected_code_1c: str | None = Field(None, max_length=255)
    expected_name: str | None = Field(None, max_length=1024)
    expected_item_id: UUID | None = None

    label_status: GoldLabelStatus
    labeler_notes: str | None = Field(None, max_length=2048)

    spec_item_id: UUID | None = None


class GoldRowFromSpecItem(BaseModel):
    """Тело POST /gold-rows/from-spec-item — посев строки из строки спеки.

    Клиентские поля копируются из spec_item. Эталон берётся из выбранной
    позиции (verification.chosen_item), либо из явно переданного
    expected_item_id. label_status по умолчанию выводится из наличия эталона.
    """

    spec_item_id: UUID
    expected_item_id: UUID | None = None
    label_status: GoldLabelStatus | None = None
    labeler_notes: str | None = Field(None, max_length=2048)


class GoldRowUpdate(BaseModel):
    """Тело PATCH /gold-rows/{id} — все поля опциональны."""

    source_file: str | None = Field(None, max_length=512)
    name: str | None = Field(None, min_length=1, max_length=1024)
    article: str | None = Field(None, max_length=255)
    manufacturer: str | None = Field(None, max_length=255)
    attributes: str | None = Field(None, max_length=2048)
    quantity: float | None = None
    unit: str | None = Field(None, max_length=64)

    expected_article: str | None = Field(None, max_length=255)
    expected_code_1c: str | None = Field(None, max_length=255)
    expected_name: str | None = Field(None, max_length=1024)
    expected_item_id: UUID | None = None

    label_status: GoldLabelStatus | None = None
    labeler_notes: str | None = Field(None, max_length=2048)


class GoldRowRead(BaseModel):
    """Ответ GET /gold-rows и GET /gold-rows/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_file: str | None
    name: str
    article: str | None
    manufacturer: str | None
    attributes: str | None
    quantity: float | None
    unit: str | None

    expected_article: str | None
    expected_code_1c: str | None
    expected_name: str | None
    expected_item_id: UUID | None

    label_status: GoldLabelStatus
    labeler_notes: str | None

    spec_item_id: UUID | None
    created_at: datetime
    updated_at: datetime
