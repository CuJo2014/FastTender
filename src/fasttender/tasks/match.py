"""Задача матчинга (раздел 7.3, шаг matched; алгоритм — раздел 9).

TODO Phase 1: реализация после готовности services/matcher.
"""

from uuid import UUID

from fasttender.core.celery_app import celery_app
from fasttender.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(name="fasttender.match_specification", bind=True)
def match_specification(self, spec_id: str) -> dict:  # type: ignore[no-untyped-def]
    spec_uuid = UUID(spec_id)
    logger.info("match_specification.start", spec_id=str(spec_uuid))
    # TODO: MatchingEngine + SearchRepository
    return {"spec_id": str(spec_uuid), "status": "stub"}
