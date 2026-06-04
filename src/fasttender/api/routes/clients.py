"""Справочник клиентов-заказчиков (CRUD)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.core.db import get_session
from fasttender.models import Client, Specification
from fasttender.schemas.client import ClientCreate, ClientRead, ClientUpdate

router = APIRouter(prefix="/clients", tags=["clients"])


async def _spec_counts(session: AsyncSession) -> dict[UUID, int]:
    """client_id → число спецификаций (для счётчика и защиты при удалении)."""
    rows = (
        await session.execute(
            select(Specification.client_id, func.count(Specification.id))
            .where(Specification.client_id.is_not(None))
            .group_by(Specification.client_id)
        )
    ).all()
    return {cid: n for cid, n in rows if cid is not None}


@router.get("/", response_model=list[ClientRead], summary="Список/поиск клиентов")
async def list_clients(
    q: str | None = Query(None, description="Поиск по имени (ILIKE)"),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[ClientRead]:
    stmt = select(Client).order_by(Client.name).limit(limit)
    if q:
        stmt = stmt.where(Client.name.ilike(f"%{q}%"))
    clients = list((await session.scalars(stmt)).all())
    counts = await _spec_counts(session)
    out: list[ClientRead] = []
    for c in clients:
        read = ClientRead.model_validate(c)
        read.specifications_count = counts.get(c.id, 0)
        out.append(read)
    return out


@router.post(
    "/",
    response_model=ClientRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать клиента",
)
async def create_client(
    payload: ClientCreate,
    session: AsyncSession = Depends(get_session),
) -> Client:
    client = Client(
        name=payload.name.strip(),
        inn=payload.inn,
        contact=payload.contact,
        notes=payload.notes,
        meta=dict(payload.meta),
    )
    session.add(client)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Клиент с таким именем уже существует"},
        ) from exc
    await session.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientRead, summary="Клиент")
async def get_client(
    client_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ClientRead:
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Клиент не найден"},
        )
    counts = await _spec_counts(session)
    read = ClientRead.model_validate(client)
    read.specifications_count = counts.get(client.id, 0)
    return read


@router.patch("/{client_id}", response_model=ClientRead, summary="Изменить клиента")
async def update_client(
    client_id: UUID,
    payload: ClientUpdate,
    session: AsyncSession = Depends(get_session),
) -> Client:
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Клиент не найден"},
        )
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        client.name = data["name"].strip()
    for field in ("inn", "contact", "notes", "meta"):
        if field in data:
            setattr(client, field, data[field])
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Клиент с таким именем уже существует"},
        ) from exc
    await session.refresh(client)
    return client


@router.delete(
    "/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить клиента (спецификации отвязываются, client_id → NULL)",
)
async def delete_client(
    client_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Клиент не найден"},
        )
    # FK ondelete=SET NULL: спецификации не удаляются, лишь отвязываются
    # (client_name остаётся как legacy-подпись).
    await session.delete(client)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
