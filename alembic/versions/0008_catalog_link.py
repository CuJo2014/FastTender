"""Item.linked_catalog_item_id + Item.catalog_link_source — связка прайс↔каталог.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-30

Один и тот же физический товар часто есть и в каталоге компании
(carteчка с Кодом 1С), и в нескольких прайсах поставщиков (предложения
по цене). Связка позволяет:
  - показать менеджеру при работе со спецификацией «вот наш товар
    Ц0000001234, к нему есть 3 предложения от поставщиков по 100/95/110»;
  - не считать прайс-позицию «потерянной» если она уже в каталоге.

Стратегия связки:
  - linked_catalog_item_id — FK на item.id (тот же таблицу), ON DELETE SET NULL
  - catalog_link_source: 'auto' (нашли при импорте) | 'manual' (менеджер выбрал)
    NULL = не связано.

`manual` lock защищает выбор менеджера от перетирания при следующем
re-import прайса. `auto` — переопределяется на каждом импорте.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "item",
        sa.Column("linked_catalog_item_id", PgUUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "item",
        sa.Column("catalog_link_source", sa.String(8), nullable=True),
    )
    # FK на ту же таблицу. ON DELETE SET NULL — если каталог-карточку удалили,
    # прайс-позиции не должны каскадно умирать.
    op.create_foreign_key(
        "fk_item_linked_catalog",
        "item",
        "item",
        ["linked_catalog_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_item_linked_catalog_item_id",
        "item",
        ["linked_catalog_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_item_linked_catalog_item_id", table_name="item")
    op.drop_constraint("fk_item_linked_catalog", "item", type_="foreignkey")
    op.drop_column("item", "catalog_link_source")
    op.drop_column("item", "linked_catalog_item_id")
