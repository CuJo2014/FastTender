"""Задача парсинга спецификации (раздел 7.3, шаг parsing).

TODO Phase 1: реализация после готовности services/parser.
"""

from uuid import UUID

from fasttender.core.celery_app import celery_app
from fasttender.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(name="fasttender.parse_specification", bind=True)
def parse_specification(self, spec_id: str) -> dict:  # type: ignore[no-untyped-def]
    """Парсит файл спецификации, заполняет SPEC_ITEM."""
    spec_uuid = UUID(spec_id)
    logger.info("parse_specification.start", spec_id=str(spec_uuid), task_id=self.request.id)
    # TODO: подключить ParserService после готовности services/parser/
    return {"spec_id": str(spec_uuid), "status": "stub"}
