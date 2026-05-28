"""Initial schema: расширения pg_trgm/btree_gin, все таблицы Фазы 1, индексы поиска.

Revision ID: 0001
Revises:
Create Date: 2026-05-28

Структура: раздел 8.1 архитектурного документа.
Индексы поиска: раздел 12.2.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Расширения PostgreSQL (раздел 12.2) ---
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")

    # --- ENUM-типы ---
    data_source_type = postgresql.ENUM(
        "company_catalog",
        "supplier_pricelist",
        "web_scraper",
        name="data_source_type",
        create_type=True,
    )
    data_source_type.create(op.get_bind(), checkfirst=True)

    data_source_status = postgresql.ENUM(
        "active", "paused", "error",
        name="data_source_status",
        create_type=True,
    )
    data_source_status.create(op.get_bind(), checkfirst=True)

    specification_status = postgresql.ENUM(
        "uploaded", "parsing", "parse_failed", "parsed",
        "matching", "match_failed", "matched",
        "reviewing", "verified", "exported",
        name="specification_status",
        create_type=True,
    )
    specification_status.create(op.get_bind(), checkfirst=True)

    match_type = postgresql.ENUM(
        "exact_article", "fuzzy_article", "lexical", "semantic", "hybrid",
        name="match_type",
        create_type=True,
    )
    match_type.create(op.get_bind(), checkfirst=True)

    verification_decision = postgresql.ENUM(
        "confirmed", "rejected", "not_found", "new_item_requested",
        name="verification_decision",
        create_type=True,
    )
    verification_decision.create(op.get_bind(), checkfirst=True)

    # --- SUPPLIER ---
    op.create_table(
        "supplier",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("meta", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    # --- DATA_SOURCE ---
    op.create_table(
        "data_source",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("type",
                  postgresql.ENUM(name="data_source_type", create_type=False),
                  nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("supplier.id", ondelete="CASCADE"), nullable=True),
        sa.Column("config", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("status",
                  postgresql.ENUM(name="data_source_status", create_type=False),
                  nullable=False, server_default="active"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_data_source_type", "data_source", ["type"])

    # --- ITEM ---
    op.create_table(
        "item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("data_source.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_raw", sa.String(255), nullable=True),
        sa.Column("article_normalized", sa.String(255), nullable=True),
        sa.Column("name", sa.String(1024), nullable=False),
        sa.Column("name_normalized", sa.String(1024), nullable=True),
        sa.Column("manufacturer", sa.String(255), nullable=True),
        sa.Column("manufacturer_normalized", sa.String(255), nullable=True),
        sa.Column("price", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("in_stock", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("attributes", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_item_source_id", "item", ["source_id"])
    op.create_index("ix_item_article_normalized", "item", ["article_normalized"])
    op.create_index("ix_item_is_active", "item", ["is_active"])

    # --- Индексы поиска (раздел 12.2) ---
    # Нечёткий поиск по артикулу — pg_trgm GIN
    op.execute(
        "CREATE INDEX ix_item_article_trgm "
        "ON item USING gin (article_normalized gin_trgm_ops) "
        "WHERE article_normalized IS NOT NULL"
    )
    # Нечёткий поиск по нормализованному наименованию
    op.execute(
        "CREATE INDEX ix_item_name_trgm "
        "ON item USING gin (name_normalized gin_trgm_ops) "
        "WHERE name_normalized IS NOT NULL"
    )
    # Generated column tsvector для полнотекстового поиска (раздел 12.2)
    op.execute(
        "ALTER TABLE item ADD COLUMN name_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('russian', coalesce(name_normalized, name))) STORED"
    )
    op.execute("CREATE INDEX ix_item_name_tsv ON item USING gin (name_tsv)")

    # --- SPECIFICATION ---
    op.create_table(
        "specification",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("source_filename", sa.String(512), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column("status",
                  postgresql.ENUM(name="specification_status", create_type=False),
                  nullable=False, server_default="uploaded"),
        sa.Column("error_message", sa.String(2048), nullable=True),
        sa.Column("meta", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_specification_status", "specification", ["status"])

    # --- SPEC_ITEM ---
    op.create_table(
        "spec_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("spec_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("specification.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_number", sa.Integer, nullable=False),
        sa.Column("name_raw", sa.String(1024), nullable=False),
        sa.Column("article_raw", sa.String(255), nullable=True),
        sa.Column("manufacturer_raw", sa.String(255), nullable=True),
        sa.Column("unit_raw", sa.String(64), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("price_raw", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency_raw", sa.String(16), nullable=True),
        sa.Column("notes", sa.String(2048), nullable=True),
        sa.Column("name_normalized", sa.String(1024), nullable=True),
        sa.Column("article_normalized", sa.String(255), nullable=True),
        sa.Column("unit_normalized", sa.String(32), nullable=True),
        sa.Column("raw_row", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_spec_item_spec_id", "spec_item", ["spec_id"])
    op.create_unique_constraint("uq_spec_item_spec_line",
                                "spec_item", ["spec_id", "line_number"])

    # --- MATCH_CANDIDATE ---
    op.create_table(
        "match_candidate",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("spec_item_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("spec_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("match_type",
                  postgresql.ENUM(name="match_type", create_type=False),
                  nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("explanation", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_match_candidate_spec_item_id", "match_candidate", ["spec_item_id"])
    op.create_index("ix_match_candidate_item_id", "match_candidate", ["item_id"])

    # --- VERIFICATION ---
    op.create_table(
        "verification",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("spec_item_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("spec_item.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("chosen_item_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("item.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision",
                  postgresql.ENUM(name="verification_decision", create_type=False),
                  nullable=False),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("notes", sa.String(2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("verification")
    op.drop_table("match_candidate")
    op.drop_index("ix_spec_item_spec_id", table_name="spec_item")
    op.drop_table("spec_item")
    op.drop_index("ix_specification_status", table_name="specification")
    op.drop_table("specification")
    op.execute("DROP INDEX IF EXISTS ix_item_name_tsv")
    op.execute("ALTER TABLE item DROP COLUMN IF EXISTS name_tsv")
    op.execute("DROP INDEX IF EXISTS ix_item_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_item_article_trgm")
    op.drop_table("item")
    op.drop_index("ix_data_source_type", table_name="data_source")
    op.drop_table("data_source")
    op.drop_table("supplier")

    for name in (
        "verification_decision",
        "match_type",
        "specification_status",
        "data_source_status",
        "data_source_type",
    ):
        op.execute(f"DROP TYPE IF EXISTS {name}")
