"""Item: category_path для иерархии групп товаров из 1С.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-29

Phase 1 решение (см. обсуждение от 2026-05-29): иерархия групп
сохраняется одной строкой-путём («Крепёж / Болты / DIN 933»), без
нормализованной таблицы Category. Матчер пока её не использует —
поле для UI/отчётов/будущего бустинга Phase 2.

Без индекса намеренно: запросы по category_path в Phase 1 не
выполняются, индекс — пустой оверхед на запись.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "item",
        sa.Column("category_path", sa.String(1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("item", "category_path")
