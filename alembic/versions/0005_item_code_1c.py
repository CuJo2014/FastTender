"""Item: code_1c — внутренний идентификатор 1С (отдельно от Артикула).

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-29

Обсуждение 2026-05-29: в 1С есть два разных идентификатора —
**Артикул** (артикул производителя, может быть NULL, может дублироваться)
и **Код** (внутренний ID 1С, всегда заполнен, уникален). Клиенты в
спецификациях используют именно Артикул. До этой миграции мы складывали
оба в одно поле `article_raw`, что блокировало exact-match при
поиске по реальному артикулу.

Теперь:
  - `article_raw/normalized` — Артикул производителя (опционально, для матчинга)
  - `code_1c` — внутренний код 1С (опционально, для стабильной ссылки и интеграций)

Уникальность Кода 1С в рамках источника гарантируется самим 1С.
Соблюдаем семантику тем же partial unique index'ом, что и для артикула
(WHERE is_active=true, чтобы REPLACE-импорт переживал повторные заливки).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "item",
        sa.Column("code_1c", sa.String(255), nullable=True),
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_item_source_code_1c "
        "ON item (source_id, code_1c) "
        "WHERE code_1c IS NOT NULL AND is_active = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_item_source_code_1c")
    op.drop_column("item", "code_1c")
