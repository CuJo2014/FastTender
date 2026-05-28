"""Celery-задача полного пайплайна обработки одной спецификации.

В Фазе 1 — одна задача делает parse_and_normalize + match. Если потом
понадобится разделить (например, чтобы запускать матчинг параллельно по
батчам), это будет неинвазивный рефакторинг — статусы и persistence
уже разделены внутри SpecificationProcessor.
"""

import asyncio
import threading
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fasttender.core.celery_app import celery_app
from fasttender.core.config import get_settings
from fasttender.core.logging import get_logger
from fasttender.services.pipeline import process_specification_by_id

logger = get_logger(__name__)


@celery_app.task(name="fasttender.process_specification", bind=True, max_retries=3)
def process_specification(self, spec_id: str) -> dict:  # type: ignore[no-untyped-def]
    """Полный pipeline для одной спецификации (sync wrapper для Celery).

    Создаёт собственную async-сессию. Worker — sync-процесс, поэтому
    обычный путь — `asyncio.run`. Но в тестах с `task_always_eager=True`
    задача может быть вызвана из контекста уже запущенного event loop
    (async-тест) — там `asyncio.run` падает. Для этого случая запускаем
    в отдельном потоке с собственным loop.
    """
    spec_uuid = UUID(spec_id)
    logger.info("celery.process_specification.start", spec_id=str(spec_uuid))

    try:
        result = _run_sync(spec_uuid)
    except Exception as exc:
        logger.exception("celery.process_specification.failed", spec_id=str(spec_uuid))
        raise self.retry(exc=exc, countdown=10) from exc

    logger.info(
        "celery.process_specification.done",
        spec_id=str(spec_uuid),
        status=result["status"],
    )
    return result


def _run_sync(spec_id: UUID) -> dict:
    """Запускает `_run` синхронно, ужимаясь к доступному event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Нормальный путь: loop'а нет, можем использовать asyncio.run
        return asyncio.run(_run(spec_id))

    # Уже внутри loop'а (eager-режим из async-теста) — поднимаем поток
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, BaseException] = {}

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result_holder["v"] = loop.run_until_complete(_run(spec_id))
        except BaseException as e:
            error_holder["e"] = e
        finally:
            loop.close()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "e" in error_holder:
        raise error_holder["e"]
    return result_holder["v"]


async def _run(spec_id: UUID) -> dict:
    """Создаёт собственный engine на время одного запуска.

    Не используем глобальный get_engine() — он привязан к event loop'у
    web-приложения, и попытка пересечь loop'ы порождает «Event loop is
    closed» при сборе мусора asyncpg-соединений. Локальный engine,
    созданный и закрытый внутри одного `_run`, эту проблему обходит.
    """
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url_str,
        pool_pre_ping=True,
        # Small pool — каждая задача процессит одну спецификацию
        pool_size=2,
        max_overflow=2,
    )
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            spec = await process_specification_by_id(session, spec_id)
            return {
                "spec_id": str(spec.id),
                "status": spec.status.value,
                "error_message": spec.error_message,
            }
    finally:
        await engine.dispose()
