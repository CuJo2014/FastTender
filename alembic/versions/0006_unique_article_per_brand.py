"""Item: уникальность артикула — отдельно по бренду (а не глобально).

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-30

Реальные каталоги содержат **одинаковые артикулы у разных производителей**
для разных товаров (стандартные артикулы крепежа, маркировки и т.п.).
Старый индекс `ux_item_source_article` (миграция 0004) запрещал любые
дубли артикула в источнике, из-за чего такие позиции терялись при
импорте как «дубликаты».

Новая модель уникальности:
  1. **Код 1С** — реальный первичный ключ (ux_item_source_code_1c, миграция 0005)
  2. **Артикул + Бренд** — fallback для источников БЕЗ code_1c (например
     прайс-листы поставщиков без 1С). Один и тот же артикул у разных
     брендов = разные товары, оба сохраняются.

Если у позиции нет ни code_1c, ни manufacturer — она дедуплицируется
только по артикулу. Если совсем ничего нет — каждая строка считается
уникальной (importer не дедуплицирует).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Старый строгий индекс на артикул — больше не подходит реальности
    op.execute("DROP INDEX IF EXISTS ux_item_source_article")

    # Новый fallback-индекс на (артикул + бренд), только когда code_1c нет.
    # Если code_1c есть — он первичный, артикул может дублироваться свободно.
    op.execute(
        "CREATE UNIQUE INDEX ux_item_source_article_brand_no_code "
        "ON item (source_id, article_normalized, "
        "         COALESCE(lower(manufacturer), '')) "
        "WHERE article_normalized IS NOT NULL "
        "  AND code_1c IS NULL "
        "  AND is_active = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_item_source_article_brand_no_code")
    op.execute(
        "CREATE UNIQUE INDEX ux_item_source_article "
        "ON item (source_id, article_normalized) "
        "WHERE article_normalized IS NOT NULL AND is_active = true"
    )
