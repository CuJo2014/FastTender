"""Specification.bookmarked_item_id — закладка строки (одна на спеку).

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-11

Менеджер может пометить одну строку спецификации «закладкой», чтобы при
повторном открытии большой спеки быстро к ней вернуться. ON DELETE SET NULL:
если строку удалят (например, при повторном парсинге), закладка просто
снимется.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "specification",
        sa.Column("bookmarked_item_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_specification_bookmarked_item",
        "specification",
        "spec_item",
        ["bookmarked_item_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_specification_bookmarked_item", "specification", type_="foreignkey"
    )
    op.drop_column("specification", "bookmarked_item_id")
