"""Источник данных (раздел 8.1, 8.2).

Принципиальное решение: каталог компании, прайсы поставщиков и веб-скраперы —
три варианта одной сущности DATA_SOURCE. Это позволяет Matching Engine
работать единообразно вне зависимости от происхождения позиции.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from fasttender.models.enums import DataSourceStatus, DataSourceType

if TYPE_CHECKING:
    from fasttender.models.item import Item
    from fasttender.models.supplier import Supplier


class DataSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "data_source"

    type: Mapped[DataSourceType] = mapped_column(
        Enum(DataSourceType, name="data_source_type"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    supplier_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("supplier.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Для прайсов: маппинг колонок, частота обновления, валюта по умолчанию.
    # Для web_scraper (Фаза 2): URL, селекторы, расписание.
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    status: Mapped[DataSourceStatus] = mapped_column(
        Enum(DataSourceStatus, name="data_source_status"),
        nullable=False,
        default=DataSourceStatus.ACTIVE,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supplier: Mapped["Supplier | None"] = relationship(back_populates="data_sources")
    items: Mapped[list["Item"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<DataSource {self.type.value} {self.name!r}>"
