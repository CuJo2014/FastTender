"""Справочник торговых площадок (ЭТП) — CRUD."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.core.db import get_session
from fasttender.models import Specification, TradingPlatform
from fasttender.schemas.trading_platform import (
    TradingPlatformCreate,
    TradingPlatformRead,
    TradingPlatformUpdate,
)

router = APIRouter(prefix="/trading-platforms", tags=["trading-platforms"])


async def _spec_counts(session: AsyncSession) -> dict[UUID, int]:
    rows = (
        await session.execute(
            select(Specification.trading_platform_id, func.count(Specification.id))
            .where(Specification.trading_platform_id.is_not(None))
            .group_by(Specification.trading_platform_id)
        )
    ).all()
    return {pid: n for pid, n in rows if pid is not None}


@router.get("/", response_model=list[TradingPlatformRead], summary="Список/поиск площадок")
async def list_platforms(
    q: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[TradingPlatformRead]:
    stmt = select(TradingPlatform).order_by(TradingPlatform.name).limit(limit)
    if q:
        stmt = stmt.where(TradingPlatform.name.ilike(f"%{q}%"))
    platforms = list((await session.scalars(stmt)).all())
    counts = await _spec_counts(session)
    out: list[TradingPlatformRead] = []
    for p in platforms:
        read = TradingPlatformRead.model_validate(p)
        read.specifications_count = counts.get(p.id, 0)
        out.append(read)
    return out


@router.post(
    "/",
    response_model=TradingPlatformRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать площадку",
)
async def create_platform(
    payload: TradingPlatformCreate,
    session: AsyncSession = Depends(get_session),
) -> TradingPlatform:
    platform = TradingPlatform(
        name=payload.name.strip(),
        url=payload.url,
        notes=payload.notes,
        meta=dict(payload.meta),
    )
    session.add(platform)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Площадка с таким именем уже существует"},
        ) from exc
    await session.refresh(platform)
    return platform


@router.get("/{platform_id}", response_model=TradingPlatformRead, summary="Площадка")
async def get_platform(
    platform_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TradingPlatformRead:
    platform = await session.get(TradingPlatform, platform_id)
    if platform is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Площадка не найдена"},
        )
    counts = await _spec_counts(session)
    read = TradingPlatformRead.model_validate(platform)
    read.specifications_count = counts.get(platform.id, 0)
    return read


@router.patch("/{platform_id}", response_model=TradingPlatformRead, summary="Изменить площадку")
async def update_platform(
    platform_id: UUID,
    payload: TradingPlatformUpdate,
    session: AsyncSession = Depends(get_session),
) -> TradingPlatform:
    platform = await session.get(TradingPlatform, platform_id)
    if platform is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Площадка не найдена"},
        )
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        platform.name = data["name"].strip()
    for field in ("url", "notes", "meta"):
        if field in data:
            setattr(platform, field, data[field])
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Площадка с таким именем уже существует"},
        ) from exc
    await session.refresh(platform)
    return platform


@router.delete(
    "/{platform_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить площадку (спеки отвязываются, trading_platform_id → NULL)",
)
async def delete_platform(
    platform_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    platform = await session.get(TradingPlatform, platform_id)
    if platform is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Площадка не найдена"},
        )
    await session.delete(platform)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
