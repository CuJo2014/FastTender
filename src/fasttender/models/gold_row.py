"""Строка золотого датасета — эталон для оценки матчера (раздел 15.4, 16.3).

Снимок «строка спецификации → правильная позиция каталога», размеченный
вручную. Хранится ОТДЕЛЬНО от операционных `Verification`: золотой датасет —
стабильный эталон для метрик (Recall@K / Precision@1 / MRR), он не должен
меняться при пере-матчинге или перезагрузке каталога. Поэтому эталонная
разметка хранится денормализованным снимком (`expected_article`,
`expected_code_1c`, `expected_name`), а не только FK на каталог.

Колонки 1-в-1 повторяют Excel-шаблон (см. `eval_gold.GoldRow` и Приложение
C.3), поэтому экспорт в шаблон тривиален и CLI-прогон `eval_gold.py` работает
без изменений.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fasttender.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from fasttender.models.enums import GoldLabelStatus

if TYPE_CHECKING:
    from fasttender.models.item import Item
    from fasttender.models.spec_item import SpecItem


class GoldRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "gold_row"

    # --- Исходные данные (как в спецификации клиента) ---
    source_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    name: Mapped[str] = mapped_column(String(1024), nullable=False)
    article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attributes: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Эталонная разметка (снимок, не зависит от состояния каталога) ---
    expected_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_code_1c: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_name: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    label_status: Mapped[GoldLabelStatus] = mapped_column(
        Enum(
            GoldLabelStatus,
            name="gold_label_status",
            values_callable=lambda enum: [e.value for e in enum],
            create_type=False,
        ),
        nullable=False,
    )
    labeler_notes: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # --- Провенанс (опционально; ON DELETE SET NULL — не рушит эталон при
    #     удалении исходной спеки/каталога) ---
    spec_item_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("spec_item.id", ondelete="SET NULL"),
        nullable=True,
    )
    expected_item_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("item.id", ondelete="SET NULL"),
        nullable=True,
    )

    expected_item: Mapped["Item | None"] = relationship()
    spec_item: Mapped["SpecItem | None"] = relationship()

    def __repr__(self) -> str:
        return f"<GoldRow {self.label_status.value} {self.name[:40]!r}>"
