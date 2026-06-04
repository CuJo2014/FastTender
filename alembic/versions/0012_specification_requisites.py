"""Реквизиты спецификации: торговая площадка, номер, дата, дата поставки.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-04

Запрошено заказчиком: к спецификации добавить реквизиты тендера —
«Торговая площадка», «Номер», «Дата», «Дата поставки». Отдельные
типизированные колонки (даты — DATE), все nullable.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("specification", sa.Column("trading_platform", sa.String(255), nullable=True))
    op.add_column("specification", sa.Column("spec_number", sa.String(128), nullable=True))
    op.add_column("specification", sa.Column("spec_date", sa.Date(), nullable=True))
    op.add_column("specification", sa.Column("delivery_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("specification", "delivery_date")
    op.drop_column("specification", "spec_date")
    op.drop_column("specification", "spec_number")
    op.drop_column("specification", "trading_platform")
