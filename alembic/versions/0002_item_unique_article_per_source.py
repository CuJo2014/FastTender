"""Item: partial unique index на (source_id, article_normalized).

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-28

Внутри одного источника (каталог компании, прайс конкретного поставщика)
артикул должен быть уникален. NULL артикулы допустимы и не участвуют в индексе.

Назначение:
  - Защитный инвариант от программных ошибок (двойной импорт строки).
  - Позволяет использовать ON CONFLICT для UPSERT в импортере при необходимости.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX ux_item_source_article "
        "ON item (source_id, article_normalized) "
        "WHERE article_normalized IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_item_source_article")
