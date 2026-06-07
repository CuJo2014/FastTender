"""Золотой датасет — ввод и хранение эталонных строк (раздел 15.4, 16.3).

Источник истины для метрик матчера. Хранится отдельно от операционных
verification; CLI-прогон `eval_gold.py` читает экспортированный отсюда Excel.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fasttender.core.db import get_session
from fasttender.models import GoldLabelStatus, GoldRow, Item, SpecItem
from fasttender.models.specification import Specification
from fasttender.models.verification import Verification
from fasttender.schemas.gold import (
    GoldRowCreate,
    GoldRowFromSpecItem,
    GoldRowRead,
    GoldRowUpdate,
)
from fasttender.services.gold_export import build_gold_xlsx

router = APIRouter(prefix="/gold-rows", tags=["gold"])


async def _load_expected_item(session: AsyncSession, item_id: UUID) -> Item:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Позиция каталога не найдена"},
        )
    return item


def _apply_expected_snapshot(row: GoldRow, item: Item) -> None:
    """Снимает эталон из позиции каталога в денормализованные поля."""
    row.expected_item_id = item.id
    row.expected_article = item.article_raw
    row.expected_code_1c = item.code_1c
    row.expected_name = item.name


# --- Список ---


@router.get("/", response_model=list[GoldRowRead], summary="Список строк gold dataset")
async def list_gold_rows(
    label_status: GoldLabelStatus | None = Query(None, description="Фильтр по статусу разметки"),
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
) -> list[GoldRow]:
    stmt = select(GoldRow).order_by(GoldRow.created_at).limit(limit)
    if label_status is not None:
        stmt = stmt.where(GoldRow.label_status == label_status)
    return list((await session.scalars(stmt)).all())


# --- Экспорт в Excel-шаблон (до /{gold_id}, чтобы не перехватился) ---


@router.get("/export.xlsx", summary="Выгрузить gold dataset в Excel-шаблон")
async def export_gold_rows(
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    rows = list((await session.scalars(select(GoldRow).order_by(GoldRow.created_at))).all())
    content = build_gold_xlsx(rows)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"gold_dataset_{stamp}.xlsx"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Создание ---


@router.post(
    "/",
    response_model=GoldRowRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать строку gold dataset (ручной ввод)",
)
async def create_gold_row(
    payload: GoldRowCreate,
    session: AsyncSession = Depends(get_session),
) -> GoldRow:
    row = GoldRow(
        source_file=payload.source_file,
        name=payload.name.strip(),
        article=payload.article,
        manufacturer=payload.manufacturer,
        attributes=payload.attributes,
        quantity=payload.quantity,
        unit=payload.unit,
        expected_article=payload.expected_article,
        expected_code_1c=payload.expected_code_1c,
        expected_name=payload.expected_name,
        label_status=payload.label_status,
        labeler_notes=payload.labeler_notes,
        spec_item_id=payload.spec_item_id,
    )
    if payload.expected_item_id is not None:
        item = await _load_expected_item(session, payload.expected_item_id)
        _apply_expected_snapshot(row, item)
        # Явно переданные expected_* имеют приоритет над снимком
        if payload.expected_article is not None:
            row.expected_article = payload.expected_article
        if payload.expected_code_1c is not None:
            row.expected_code_1c = payload.expected_code_1c
        if payload.expected_name is not None:
            row.expected_name = payload.expected_name

    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.post(
    "/from-spec-item",
    response_model=GoldRowRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать строку gold dataset из строки спецификации",
)
async def create_gold_row_from_spec_item(
    payload: GoldRowFromSpecItem,
    session: AsyncSession = Depends(get_session),
) -> GoldRow:
    spec_item = (
        await session.scalars(
            select(SpecItem)
            .where(SpecItem.id == payload.spec_item_id)
            .options(
                selectinload(SpecItem.specification),
                selectinload(SpecItem.verification).selectinload(Verification.chosen_item),
            )
        )
    ).one_or_none()
    if spec_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Строка спецификации не найдена"},
        )

    spec: Specification | None = spec_item.specification
    row = GoldRow(
        source_file=spec.source_filename if spec else None,
        name=spec_item.name_raw,
        article=spec_item.article_raw,
        manufacturer=spec_item.manufacturer_raw,
        attributes=None,
        quantity=float(spec_item.quantity) if spec_item.quantity is not None else None,
        unit=spec_item.unit_raw,
        labeler_notes=payload.labeler_notes,
        spec_item_id=spec_item.id,
        # Заполним ниже
        label_status=GoldLabelStatus.NOT_FOUND,
    )

    # Эталон: явный expected_item_id важнее выбранной позиции верификации
    expected: Item | None = None
    if payload.expected_item_id is not None:
        expected = await _load_expected_item(session, payload.expected_item_id)
    elif spec_item.verification is not None and spec_item.verification.chosen_item is not None:
        expected = spec_item.verification.chosen_item

    if expected is not None:
        _apply_expected_snapshot(row, expected)

    # Статус: явный приоритетнее; иначе выводим из наличия эталона
    if payload.label_status is not None:
        row.label_status = payload.label_status
    elif expected is not None:
        row.label_status = GoldLabelStatus.FOUND

    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


# --- Чтение / изменение / удаление ---


@router.get("/{gold_id}", response_model=GoldRowRead, summary="Строка gold dataset")
async def get_gold_row(
    gold_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> GoldRow:
    row = await session.get(GoldRow, gold_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Строка не найдена"},
        )
    return row


@router.patch("/{gold_id}", response_model=GoldRowRead, summary="Изменить строку gold dataset")
async def update_gold_row(
    gold_id: UUID,
    payload: GoldRowUpdate,
    session: AsyncSession = Depends(get_session),
) -> GoldRow:
    row = await session.get(GoldRow, gold_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Строка не найдена"},
        )

    data = payload.model_dump(exclude_unset=True)

    # Если меняют expected_item_id — снимаем новый снимок из каталога
    if "expected_item_id" in data:
        if data["expected_item_id"] is not None:
            item = await _load_expected_item(session, data["expected_item_id"])
            _apply_expected_snapshot(row, item)
        else:
            row.expected_item_id = None

    simple_fields = (
        "source_file",
        "article",
        "manufacturer",
        "attributes",
        "quantity",
        "unit",
        "expected_article",
        "expected_code_1c",
        "expected_name",
        "label_status",
        "labeler_notes",
    )
    for field in simple_fields:
        if field in data:
            setattr(row, field, data[field])
    if "name" in data and data["name"] is not None:
        row.name = data["name"].strip()

    await session.commit()
    await session.refresh(row)
    return row


@router.delete(
    "/{gold_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить строку gold dataset",
)
async def delete_gold_row(
    gold_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    row = await session.get(GoldRow, gold_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Строка не найдена"},
        )
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
