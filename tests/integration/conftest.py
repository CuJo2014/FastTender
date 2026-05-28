"""Фикстуры для интеграционных тестов с реальным Postgres.

Тесты автоматически пропускаются, если БД недоступна. URL берётся из
переменной окружения FT_TEST_DATABASE_URL — по умолчанию `localhost:5433`,
который docker-compose делает доступным.

Каждый тест выполняется во внешней транзакции; session-уровневые commit
становятся savepoint-релизами, а в конце теста всё откатывается, поэтому
БД остаётся неизменной между тестами.
"""

import os
import socket
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DEFAULT_TEST_URL = "postgresql+asyncpg://fasttender:fasttender@localhost:5433/fasttender"
TEST_DB_URL = os.environ.get("FT_TEST_DATABASE_URL", DEFAULT_TEST_URL)


def _is_postgres_available() -> bool:
    """Быстрая синхронная проверка доступности БД до старта тестов."""
    try:
        netloc = TEST_DB_URL.split("@", 1)[1].split("/", 1)[0]
        host, port = netloc.split(":")
        with socket.create_connection((host, int(port)), timeout=1):
            return True
    except (ValueError, OSError):
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _is_postgres_available(),
        reason=f"PostgreSQL недоступен по адресу {TEST_DB_URL} (нужен `docker compose up postgres`)",
    ),
]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Изолированная сессия: внешняя транзакция откатывается в конце теста.

    Pattern: connection.begin() → savepoint-mode session. session.commit()
    внутри теста релизит savepoint, но внешняя транзакция всё ещё открыта
    и в финале откатывается.
    """
    engine = create_async_engine(TEST_DB_URL, future=True)

    async with engine.connect() as connection:
        # На всякий случай чистим то, что могло остаться от прошлых прогонов
        await _truncate_all(connection)
        await connection.commit()

        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as s:
            try:
                yield s
            finally:
                await s.close()
        await transaction.rollback()

    await engine.dispose()


async def _truncate_all(connection) -> None:  # type: ignore[no-untyped-def]
    tables = [
        "verification",
        "match_candidate",
        "spec_item",
        "specification",
        "item",
        "data_source",
        "supplier",
    ]
    await connection.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
