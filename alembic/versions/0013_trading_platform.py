"""TradingPlatform — справочник ЭТП + specification.is_tp/trading_platform_id.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-04

Торговая площадка становится справочником (как Client). На спецификации:
- is_tp (bool) — флаг «Спецификация ТП»;
- trading_platform_id (FK → trading_platform, SET NULL) — выбранная площадка.

trading_platform (строка из 0012) остаётся денорм-именем для экспорта.
Бэкфилл: непустые trading_platform → записи TradingPlatform + проставить
trading_platform_id + is_tp=true.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trading_platform",
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
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("url", sa.String(512), nullable=True),
        sa.Column("notes", sa.String(2048), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.add_column(
        "specification",
        sa.Column("is_tp", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "specification",
        sa.Column("trading_platform_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_specification_trading_platform",
        "specification",
        "trading_platform",
        ["trading_platform_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_specification_trading_platform_id", "specification", ["trading_platform_id"]
    )

    # Бэкфилл из существующих строк trading_platform
    op.execute(
        """
        INSERT INTO trading_platform (id, created_at, updated_at, name, meta)
        SELECT gen_random_uuid(), now(), now(), s.trading_platform, '{}'::jsonb
        FROM (
            SELECT DISTINCT trading_platform FROM specification
            WHERE trading_platform IS NOT NULL AND btrim(trading_platform) <> ''
        ) s
        """
    )
    op.execute(
        """
        UPDATE specification sp
        SET trading_platform_id = tp.id, is_tp = true
        FROM trading_platform tp
        WHERE sp.trading_platform = tp.name
        """
    )

    # server_default на is_tp нужен был только для бэкфилла существующих строк
    op.alter_column("specification", "is_tp", server_default=None)


def downgrade() -> None:
    op.drop_index(
        "ix_specification_trading_platform_id", table_name="specification"
    )
    op.drop_constraint(
        "fk_specification_trading_platform", "specification", type_="foreignkey"
    )
    op.drop_column("specification", "trading_platform_id")
    op.drop_column("specification", "is_tp")
    op.drop_table("trading_platform")
