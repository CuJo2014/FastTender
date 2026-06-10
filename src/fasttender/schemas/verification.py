"""DTO для верификации позиций спецификации (раздел 4.7)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fasttender.models.enums import VerificationDecision


class VerifyRequest(BaseModel):
    """Решение менеджера по одной строке спецификации (Приложение C.4).

    Правила валидации:
      - decision = confirmed → chosen_item_id обязателен.
      - decision = rejected / not_found / new_item_requested → chosen_item_id null.
    """

    decision: VerificationDecision
    chosen_item_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=2048)
    decided_by: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _check_chosen_item(self) -> "VerifyRequest":
        if self.decision is VerificationDecision.CONFIRMED and self.chosen_item_id is None:
            raise ValueError("Для решения CONFIRMED обязательно chosen_item_id")
        if self.decision is not VerificationDecision.CONFIRMED and self.chosen_item_id is not None:
            # Не падаем — просто игнорируем, чтобы UI мог отправлять одной формой
            self.chosen_item_id = None
        return self


class VerifyResponse(BaseModel):
    """Ответ POST /verify."""

    model_config = ConfigDict(from_attributes=True)

    spec_item_id: UUID
    decision: VerificationDecision
    chosen_item_id: UUID | None = None
    decided_by: str | None = None
    notes: str | None = None
    decided_at: datetime


class AutoConfirmRequest(BaseModel):
    """Массовое авто-подтверждение позиций со «слишком высокой» уверенностью.

    По умолчанию использует confidence_auto_confirm из настроек (0.9, A3 — раздел 6.1).
    """

    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    decided_by: str | None = Field(default=None, max_length=255)
    only_unverified: bool = Field(
        default=True,
        description="Не трогать строки, по которым уже есть Verification",
    )
    dry_run: bool = Field(
        default=False,
        description="Только посчитать целевые строки, ничего не подтверждать",
    )


class AutoConfirmResponse(BaseModel):
    """Результат массового авто-подтверждения."""

    confirmed_count: int
    skipped_already_verified: int = 0
    skipped_below_threshold: int = 0
    threshold_used: float


class BulkVerifyRequest(BaseModel):
    """Массовое решение по явно выбранным строкам (чекбоксы в UI).

    Для CONFIRMED подтверждается топ-кандидат каждой строки; строки без
    кандидата пропускаются (см. skipped_no_candidate в ответе).
    """

    item_ids: list[UUID] = Field(default_factory=list)
    decision: VerificationDecision
    decided_by: str | None = Field(default=None, max_length=255)


class BulkVerifyResponse(BaseModel):
    """Результат массового решения по выбранным строкам."""

    applied: int = 0
    skipped_no_candidate: int = 0
