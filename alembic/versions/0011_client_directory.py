"""Client — справочник клиентов + specification.client_id (FK).

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-04

Клиент-заказчик становится отдельной сущностью (справочником), а не
свободной строкой в Specification.client_name. Спецификация ссылается на
клиента через FK client_id (ON DELETE SET NULL).

Бэкфилл: из существующих distinct client_name создаём записи Client и
проставляем specification.client_id. client_name оставляем как legacy/аудит.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client",
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
        sa.Column("inn", sa.String(32), nullable=True),
        sa.Column("contact", sa.String(512), nullable=True),
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
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_specification_client",
        "specification",
        "client",
        ["client_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_specification_client_id", "specification", ["client_id"])

    # Бэкфилл: distinct непустые client_name → записи Client
    op.execute(
        """
        INSERT INTO client (id, created_at, updated_at, name, meta)
        SELECT gen_random_uuid(), now(), now(), s.client_name, '{}'::jsonb
        FROM (
            SELECT DISTINCT client_name FROM specification
            WHERE client_name IS NOT NULL AND btrim(client_name) <> ''
        ) s
        """
    )
    op.execute(
        """
        UPDATE specification sp
        SET client_id = c.id
        FROM client c
        WHERE sp.client_name = c.name
        """
    )


def downgrade() -> None:
    op.drop_index("ix_specification_client_id", table_name="specification")
    op.drop_constraint("fk_specification_client", "specification", type_="foreignkey")
    op.drop_column("specification", "client_id")
    op.drop_table("client")
