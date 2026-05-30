"""Supplier.prefix + Item.supplier_sku — внутренний нумератор позиций прайсов.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-30

Идея: каждый поставщик получает короткий префикс (3 символа), и при
импорте прайса каждая позиция получает уникальный «внутренний SKU»
вида `SIB-000042` — стабильный идентификатор, к которому можно
ссылаться в КП и UI.

Назначение supplier_sku — Phase 1 НЕ-1С аналог code_1c:
у каталога компании уникальная стабильная ссылка есть (Код 1С),
у прайсов поставщиков — нет. supplier_sku заполняет этот пробел.

Поля nullable: существующие поставщики без prefix продолжают работать
без присвоения SKU. При создании нового поставщика prefix рекомендуется
указать (валидация в API), но БД не заставляет.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Префикс поставщика — 3 символа (A-Z0-9), уникальный между поставщиками
    op.add_column(
        "supplier",
        sa.Column("prefix", sa.String(3), nullable=True),
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_supplier_prefix "
        "ON supplier (prefix) "
        "WHERE prefix IS NOT NULL"
    )

    # Внутренний SKU позиции — для прайсов поставщиков. Уникален в рамках
    # источника + active.
    op.add_column(
        "item",
        sa.Column("supplier_sku", sa.String(32), nullable=True),
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_item_source_supplier_sku "
        "ON item (source_id, supplier_sku) "
        "WHERE supplier_sku IS NOT NULL AND is_active = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_item_source_supplier_sku")
    op.drop_column("item", "supplier_sku")

    op.execute("DROP INDEX IF EXISTS ux_supplier_prefix")
    op.drop_column("supplier", "prefix")
