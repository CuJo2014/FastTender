"""Единая таблица позиций — каталог + прайсы (раздел 8.1, 8.2)."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from fasttender.models.data_source import DataSource


class Item(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Позиция из любого источника (каталог компании или прайс поставщика).

    `article_normalized` и `name_normalized` — для поиска (раздел 4.2, 10.3).
    `article_raw` и `name_raw` — оригинал «как у клиента/поставщика», для UI и аудита.
    Индексы pg_trgm и tsvector создаются в миграции 0001.
    """

    __tablename__ = "item"

    source_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("data_source.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    article_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    article_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Внутренний код 1С (отдельно от Артикула — см. миграцию 0005).
    # Всегда заполнен для импорта из 1С, гарантированно уникален.
    code_1c: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Внутренний SKU позиции прайса поставщика: <prefix>-<NNNNNN>,
    # например «SIB-000042». Стабилен между пере-загрузками прайса
    # (см. миграцию 0007). Для позиций каталога компании всегда None.
    supplier_sku: Mapped[str | None] = mapped_column(String(32), nullable=True)

    name: Mapped[str] = mapped_column(String(1024), nullable=False)
    name_normalized: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Иерархия товарных групп из 1С — строка вида «Крепёж / Болты / DIN933».
    # Phase 1: только хранение, матчер не использует (раздел 4.3 / 9.2 Phase 2).
    category_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    source: Mapped["DataSource"] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"<Item {self.article_raw or '-'} {self.name[:40]!r}>"
