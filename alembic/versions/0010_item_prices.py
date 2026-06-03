"""Item.prices — несколько цен на позицию (JSONB).

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-03

В прайсах поставщиков на позицию приходится несколько цен: пары «с НДС»/
«без НДС», уровни (закупка/РРЦ/МИЦ у TEL), акция, «с ТЗР». Раньше хранили
ОДНУ `item.price` — детектор брал первую совпавшую колонку и терял
остальные, а базы НДС у разных поставщиков смешивались (gross/net) без
возможности привести к единому виду.

`prices` — JSONB-массив всех цен позиции. Элемент:
    {"amount": "22614.75", "vat": "net"|"gross"|"unknown",
     "tier": "Цены с вашей скидкой"|null, "label": "Цена без НДС, руб."|null}

`item.price` остаётся основной (preferred) ценой — проекцией для матчера,
сортировки и экспорта. История цен — отдельной таблицей позже (не сейчас).

Бэкфилл: существующим строкам ставим [] (server_default), затем снимаем
default чтобы значение всегда писалось приложением явно.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "item",
        sa.Column(
            "prices",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Дефолт нужен был только для бэкфилла существующих строк; дальше
    # значение всегда пишет приложение.
    op.alter_column("item", "prices", server_default=None)


def downgrade() -> None:
    op.drop_column("item", "prices")
