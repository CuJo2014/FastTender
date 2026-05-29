"""Item: unique артикула только среди is_active=true.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-29

Баг 0002: партиал-индекс `ux_item_source_article` отбрасывал NULL-артикулы
через `WHERE article_normalized IS NOT NULL`, но НЕ учитывал `is_active`.
В результате REPLACE-импорт каталога второй раз падал на UniqueViolation:
он сначала деактивирует старые строки (is_active=false), но они остаются
в БД для истории матчингов; новые INSERT'ы натыкаются на «занятый» артикул.

Семантика, которую мы хотели изначально: «внутри одного активного среза
источника артикул уникален». Деактивированные исторические версии могут
сосуществовать рядом — это нормально.

Исправление: индекс пересоздаём с дополнительным условием is_active=true.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_item_source_article")
    op.execute(
        "CREATE UNIQUE INDEX ux_item_source_article "
        "ON item (source_id, article_normalized) "
        "WHERE article_normalized IS NOT NULL AND is_active = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_item_source_article")
    op.execute(
        "CREATE UNIQUE INDEX ux_item_source_article "
        "ON item (source_id, article_normalized) "
        "WHERE article_normalized IS NOT NULL"
    )
