"""Health-check эндпоинты."""

from typing import Any

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.core.config import get_settings
from fasttender.core.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe — проверяет БД и Redis")
async def ready(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    settings = get_settings()
    result: dict[str, Any] = {"status": "ok", "checks": {}}

    # PostgreSQL
    try:
        await session.execute(text("SELECT 1"))
        result["checks"]["postgres"] = "ok"
    except Exception as exc:
        result["status"] = "degraded"
        result["checks"]["postgres"] = f"error: {exc}"

    # Redis
    redis = Redis.from_url(settings.redis_url_str)
    try:
        pong = await redis.ping()
        result["checks"]["redis"] = "ok" if pong else "no_pong"
    except Exception as exc:
        result["status"] = "degraded"
        result["checks"]["redis"] = f"error: {exc}"
    finally:
        await redis.aclose()

    return result
