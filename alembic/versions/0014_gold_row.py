"""GoldRow — золотой датасет (эталон для оценки матчера).

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-07

Отдельная таблица для ручной разметки «строка спецификации → правильная
позиция каталога». Хранит денормализованный снимок эталона, чтобы метрики
(Recall@K / Precision@1 / MRR) не зависели от пере-матчинга и перезагрузки
каталога. Колонки повторяют Excel-шаблон (Приложение C.3 / eval_gold.py).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    gold_label_status = postgresql.ENUM(
        "найдено",
        "аналог",
        "не найдено",
        "сомнительно",
        name="gold_label_status",
        create_type=True,
    )
    gold_label_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "gold_row",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Исходные данные (как в спецификации клиента)
        sa.Column("source_file", sa.String(512), nullable=True),
        sa.Column("name", sa.String(1024), nullable=False),
        sa.Column("article", sa.String(255), nullable=True),
        sa.Column("manufacturer", sa.String(255), nullable=True),
        sa.Column("attributes", sa.String(2048), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("unit", sa.String(64), nullable=True),
        # Эталонная разметка (снимок)
        sa.Column("expected_article", sa.String(255), nullable=True),
        sa.Column("expected_code_1c", sa.String(255), nullable=True),
        sa.Column("expected_name", sa.String(1024), nullable=True),
        sa.Column(
            "label_status",
            postgresql.ENUM(name="gold_label_status", create_type=False),
            nullable=False,
        ),
        sa.Column("labeler_notes", sa.String(2048), nullable=True),
        # Провенанс (ON DELETE SET NULL)
        sa.Column("spec_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expected_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_gold_row_spec_item",
        "gold_row",
        "spec_item",
        ["spec_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_gold_row_expected_item",
        "gold_row",
        "item",
        ["expected_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_gold_row_label_status", "gold_row", ["label_status"])


def downgrade() -> None:
    op.drop_index("ix_gold_row_label_status", table_name="gold_row")
    op.drop_table("gold_row")
    postgresql.ENUM(name="gold_label_status").drop(op.get_bind(), checkfirst=True)
