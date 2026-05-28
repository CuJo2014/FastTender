"""Задача нормализации (раздел 7.3, шаг normalized).

TODO Phase 1: реализация после готовности services/normalizer.
"""

from uuid import UUID

from fasttender.core.celery_app import celery_app
from fasttender.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(name="fasttender.normalize_specification", bind=True)
def normalize_specification(self, spec_id: str) -> dict:  # type: ignore[no-untyped-def]
    spec_uuid = UUID(spec_id)
    logger.info("normalize_specification.start", spec_id=str(spec_uuid))
    # TODO: NormalizerService
    return {"spec_id": str(spec_uuid), "status": "stub"}
