"""Строка спецификации с оригинальными и нормализованными полями (раздел 4.1.3, 8.1)."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from fasttender.models.match_candidate import MatchCandidate
    from fasttender.models.specification import Specification
    from fasttender.models.verification import Verification


class SpecItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "spec_item"

    spec_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("specification.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Сырые поля (как у клиента) — критично для аудита (раздел 4.2)
    name_raw: Mapped[str] = mapped_column(String(1024), nullable=False)
    article_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_raw: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency_raw: Mapped[str | None] = mapped_column(String(16), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Нормализованные поля
    name_normalized: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    article_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit_normalized: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Сырая исходная строка для аудита
    raw_row: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    specification: Mapped["Specification"] = relationship(back_populates="items")
    candidates: Mapped[list["MatchCandidate"]] = relationship(
        back_populates="spec_item",
        cascade="all, delete-orphan",
        order_by="MatchCandidate.rank",
    )
    verification: Mapped["Verification | None"] = relationship(
        back_populates="spec_item",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def __repr__(self) -> str:
        return f"<SpecItem #{self.line_number} {self.name_raw[:40]!r}>"
