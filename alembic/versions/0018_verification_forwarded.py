"""VerificationDecision.FORWARDED — решение «Передать» (в группу МОС).

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-11

Менеджер может пометить строку «Передать» — дальнейшая передача в отдельную
группу МОС (менеджеры отдела снабжения). Это терминальное решение (строка
считается обработанной), отдельный счётчик «Передано». Добавляем значение в
enum verification_decision (как 0009 добавлял 'cancelled' в specification_status).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE verification_decision ADD VALUE IF NOT EXISTS 'forwarded'")


def downgrade() -> None:
    # PostgreSQL не умеет удалять значение enum без пересоздания типа.
    # Откат-no-op: значение 'forwarded' остаётся в enum (безопасно — просто
    # перестаёт использоваться). Полное удаление потребовало бы пересборки
    # типа и обновления всех зависимых колонок — не делаем.
    pass
