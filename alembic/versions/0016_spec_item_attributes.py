"""SpecItem.attributes_raw — характеристики/параметры подбора из спеки.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-09

Колонка хранит распознанную из заголовка «Характеристика» строку как есть.
Используется в матчинге (подмешивается в лексический поиск). Существующим
строкам — NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "spec_item",
        sa.Column("attributes_raw", sa.String(2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("spec_item", "attributes_raw")
