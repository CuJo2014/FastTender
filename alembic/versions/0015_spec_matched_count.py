"""Specification.matched_count — прогресс матчинга (для % в UI).

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-08

Счётчик обработанных матчером строк. Обновляется батчами в
pipeline._match_all; знаменатель прогресса — число SpecItem спеки.
Существующим строкам проставляется 0 (server_default).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "specification",
        sa.Column(
            "matched_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("specification", "matched_count")
