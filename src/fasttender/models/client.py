"""Справочник клиентов (заказчиков спецификаций)."""

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from fasttender.models.specification import Specification


class Client(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Клиент-заказчик. На него ссылаются спецификации (Specification.client_id).

    Реквизиты (ИНН, контакты) и расширения (торговые площадки) — по мере
    потребности; meta оставлено под будущие поля без миграций.
    """

    __tablename__ = "client"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    inn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    specifications: Mapped[list["Specification"]] = relationship(
        back_populates="client",
    )

    def __repr__(self) -> str:
        return f"<Client {self.name!r}>"
