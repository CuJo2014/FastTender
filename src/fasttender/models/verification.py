"""Решение менеджера по строке спецификации (раздел 8.1, 8.3).

В Фазе 1 — упрощённая, без полноценного user-ID и RBAC.
В Фазе 2 — добавится связь с USER и проверка прав (раздел 5.3).
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from fasttender.models.enums import VerificationDecision

if TYPE_CHECKING:
    from fasttender.models.item import Item
    from fasttender.models.spec_item import SpecItem


class Verification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "verification"

    spec_item_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("spec_item.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    chosen_item_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("item.id", ondelete="SET NULL"),
        nullable=True,
    )

    decision: Mapped[VerificationDecision] = mapped_column(
        Enum(VerificationDecision, name="verification_decision"),
        nullable=False,
    )

    # В Фазе 1 — просто строка с именем менеджера; в Фазе 2 → FK на USER
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    spec_item: Mapped["SpecItem"] = relationship(back_populates="verification")
    chosen_item: Mapped["Item | None"] = relationship()

    def __repr__(self) -> str:
        return f"<Verification {self.decision.value} for spec_item={self.spec_item_id}>"
