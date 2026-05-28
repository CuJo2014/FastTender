"""Спецификация клиента (раздел 8.1)."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from fasttender.models.enums import SpecificationStatus

if TYPE_CHECKING:
    from fasttender.models.spec_item import SpecItem


class Specification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "specification"

    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[SpecificationStatus] = mapped_column(
        Enum(SpecificationStatus, name="specification_status"),
        nullable=False,
        default=SpecificationStatus.UPLOADED,
        index=True,
    )

    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["SpecItem"]] = relationship(
        back_populates="specification",
        cascade="all, delete-orphan",
        order_by="SpecItem.line_number",
    )

    def __repr__(self) -> str:
        return f"<Specification {self.source_filename!r} status={self.status.value}>"
