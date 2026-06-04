"""Справочник торговых площадок (ЭТП)."""

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from fasttender.models.specification import Specification


class TradingPlatform(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Торговая площадка (ЭТП). На неё ссылаются спецификации тендеров."""

    __tablename__ = "trading_platform"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    specifications: Mapped[list["Specification"]] = relationship(
        back_populates="trading_platform_ref",
    )

    def __repr__(self) -> str:
        return f"<TradingPlatform {self.name!r}>"
