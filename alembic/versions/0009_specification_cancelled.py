"""SpecificationStatus.CANCELLED — отказ менеджера от поставки.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-01

UX-фидбэк 1 июня 2026: менеджер должен иметь возможность отказаться
от спецификации целиком (понимает, что поставку обеспечить не сможет).
До этого верификация была только per-row.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE specification_status ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # PostgreSQL не поддерживает DROP VALUE из enum безопасно.
    # Если очень нужно — пересоздать тип целиком, заменив все ссылки.
    pass
