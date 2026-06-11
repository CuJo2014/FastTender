"""Спецификация клиента (раздел 8.1)."""

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from fasttender.models.enums import SpecificationStatus

if TYPE_CHECKING:
    from fasttender.models.client import Client
    from fasttender.models.spec_item import SpecItem
    from fasttender.models.trading_platform import TradingPlatform


class Specification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "specification"

    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Свободное имя клиента (legacy) — сохраняем для совместимости/аудита.
    # Основная связь — client_id на справочник Client (миграция 0011).
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("client.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Реквизиты спецификации/тендера (миграция 0012).
    # trading_platform (строка) — денорм-имя выбранной площадки (для экспорта).
    trading_platform: Mapped[str | None] = mapped_column(String(255), nullable=True)
    spec_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    spec_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Спецификация торговой площадки (миграция 0013): флаг + ссылка на справочник.
    is_tp: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trading_platform_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("trading_platform.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Закладка строки (миграция 0017): одна на спецификацию. FK на spec_item
    # с ON DELETE SET NULL — взаимная ссылка с spec_item.spec_id, поэтому
    # use_alter (констрейнт создаётся отдельным ALTER).
    bookmarked_item_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "spec_item.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_specification_bookmarked_item",
        ),
        nullable=True,
    )

    status: Mapped[SpecificationStatus] = mapped_column(
        Enum(
            SpecificationStatus,
            name="specification_status",
            values_callable=lambda enum: [e.value for e in enum],
            create_type=False,
        ),
        nullable=False,
        default=SpecificationStatus.UPLOADED,
        index=True,
    )

    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Прогресс матчинга: сколько строк уже обработано матчером (для % в UI).
    # Обновляется батчами в pipeline._match_all; знаменатель — число SpecItem.
    matched_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["SpecItem"]] = relationship(
        back_populates="specification",
        cascade="all, delete-orphan",
        order_by="SpecItem.line_number",
        # Явно указываем FK: есть второй путь specification.bookmarked_item_id →
        # spec_item.id (закладка), иначе join неоднозначен.
        foreign_keys="SpecItem.spec_id",
    )
    client: Mapped["Client | None"] = relationship(
        back_populates="specifications",
        lazy="joined",
    )
    trading_platform_ref: Mapped["TradingPlatform | None"] = relationship(
        back_populates="specifications",
        lazy="joined",
    )

    def __repr__(self) -> str:
        return f"<Specification {self.source_filename!r} status={self.status.value}>"
