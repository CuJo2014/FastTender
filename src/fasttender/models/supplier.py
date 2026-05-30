"""Поставщики (раздел 8.1)."""

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from fasttender.models.data_source import DataSource


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supplier"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 3-символьный префикс (A-Z0-9), уникальный между поставщиками. Используется
    # для генерации внутреннего SKU позиций прайса (Item.supplier_sku).
    prefix: Mapped[str | None] = mapped_column(String(3), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    data_sources: Mapped[list["DataSource"]] = relationship(
        back_populates="supplier",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Supplier {self.name!r}>"
