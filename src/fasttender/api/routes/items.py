"""Точечные операции над Item: пока только привязка к каталогу (миграция 0008)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.core.db import get_session
from fasttender.models import DataSource, DataSourceType, Item

router = APIRouter(prefix="/items", tags=["items"])


class CatalogLinkRequest(BaseModel):
    """Тело PATCH /items/{id}/catalog-link."""

    catalog_item_id: UUID | None  # None = снять связь, но залочить (manual)


class CatalogLinkResponse(BaseModel):
    item_id: UUID
    linked_catalog_item_id: UUID | None
    catalog_link_source: str | None  # 'auto' | 'manual' | None


@router.patch(
    "/{item_id}/catalog-link",
    response_model=CatalogLinkResponse,
    summary="Привязать прайс-позицию к каталог-карточке (manual lock)",
)
async def set_catalog_link(
    item_id: UUID,
    payload: CatalogLinkRequest,
    session: AsyncSession = Depends(get_session),
) -> CatalogLinkResponse:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Позиция не найдена"},
        )

    if payload.catalog_item_id is not None:
        target = await session.get(Item, payload.catalog_item_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Каталог-карточка не найдена"},
            )
        # Проверяем что target действительно из каталога компании
        catalog_id = await session.scalar(
            select(DataSource.id).where(DataSource.type == DataSourceType.COMPANY_CATALOG)
        )
        if target.source_id != catalog_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Можно ссылаться только на позиции каталога компании"},
            )

    item.linked_catalog_item_id = payload.catalog_item_id
    item.catalog_link_source = "manual"
    await session.commit()
    return CatalogLinkResponse(
        item_id=item.id,
        linked_catalog_item_id=item.linked_catalog_item_id,
        catalog_link_source=item.catalog_link_source,
    )


@router.post(
    "/{item_id}/catalog-link/auto",
    response_model=CatalogLinkResponse,
    summary="Переопределить связь автоматически (снять manual lock + re-detect)",
)
async def reset_catalog_link_to_auto(
    item_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> CatalogLinkResponse:
    from fasttender.services.importer._base import (
        _find_catalog_match,
    )

    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Позиция не найдена"},
        )

    catalog_source_id = await session.scalar(
        select(DataSource.id).where(DataSource.type == DataSourceType.COMPANY_CATALOG)
    )
    if catalog_source_id is None:
        # Каталог не загружен — просто снимаем связь
        item.linked_catalog_item_id = None
        item.catalog_link_source = None
        await session.commit()
        return CatalogLinkResponse(
            item_id=item.id,
            linked_catalog_item_id=None,
            catalog_link_source=None,
        )

    catalog_items = (
        await session.scalars(
            select(Item).where(
                Item.source_id == catalog_source_id,
                Item.is_active.is_(True),
            )
        )
    ).all()
    by_code = {c.code_1c.strip(): c for c in catalog_items if c.code_1c}
    by_art_brand: dict[tuple[str, str], Item] = {}
    by_art: dict[str, Item] = {}
    for c in catalog_items:
        if c.article_normalized:
            if c.manufacturer_normalized:
                by_art_brand[(c.article_normalized, c.manufacturer_normalized.lower())] = c
            else:
                by_art.setdefault(c.article_normalized, c)

    match = _find_catalog_match(item, by_code, by_art_brand, by_art)
    item.linked_catalog_item_id = match.id if match else None
    item.catalog_link_source = "auto" if match else None
    await session.commit()
    return CatalogLinkResponse(
        item_id=item.id,
        linked_catalog_item_id=item.linked_catalog_item_id,
        catalog_link_source=item.catalog_link_source,
    )
