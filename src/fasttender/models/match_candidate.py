"""Кандидаты матчинга для строки спецификации (раздел 8.1, 9.3)."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from fasttender.models.enums import MatchType

if TYPE_CHECKING:
    from fasttender.models.item import Item
    from fasttender.models.spec_item import SpecItem


class MatchCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "match_candidate"

    spec_item_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("spec_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    match_type: Mapped[MatchType] = mapped_column(
        Enum(MatchType, name="match_type"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    # Объяснимость (раздел 9.3) — отображается в UI при наведении на оценку
    explanation: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    spec_item: Mapped["SpecItem"] = relationship(back_populates="candidates")
    item: Mapped["Item"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<MatchCandidate rank={self.rank} confidence={self.confidence:.3f} "
            f"type={self.match_type.value}>"
        )
