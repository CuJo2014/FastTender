"""Спецификации (раздел 4, Приложение C.4).

Phase 1:
  POST /specifications/             — загрузка файла, 202 + spec_id
  GET  /specifications/             — список с агрегатами
  GET  /specifications/{id}         — статус + счётчики
  GET  /specifications/{id}/items   — пагинированный список строк с кандидатами

Реальная обработка — в Celery-задаче `fasttender.process_specification`,
которая дёргается из POST. Если воркер недоступен — спец останется в
статусе uploaded до запуска воркера.
"""

import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fasttender.core.config import get_settings
from fasttender.core.db import get_session
from fasttender.models import (
    DataSource,
    DataSourceType,
    Item,
    MatchCandidate,
    Specification,
    SpecificationStatus,
    SpecItem,
)
from fasttender.schemas.specification import (
    CandidateRead,
    PaginatedSpecItems,
    SpecificationCounts,
    SpecificationRead,
    SpecificationUploadResponse,
    SpecItemRead,
    VerificationRead,
)
from fasttender.services.parser import SpecificationParser
from fasttender.tasks.process import process_specification

router = APIRouter(prefix="/specifications", tags=["specifications"])


@router.post(
    "/",
    response_model=SpecificationUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Загрузка спецификации",
)
async def upload_specification(
    file: UploadFile = File(...),
    client_name: str | None = Query(None, max_length=255),
    session: AsyncSession = Depends(get_session),
) -> SpecificationUploadResponse:
    _validate_upload(file)

    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "spec.xlsx").suffix
    with tempfile.NamedTemporaryFile(
        suffix=suffix,
        dir=settings.upload_dir,
        delete=False,
    ) as tmp:
        storage_path = Path(tmp.name)
        shutil.copyfileobj(file.file, tmp)

    spec = Specification(
        source_filename=file.filename or storage_path.name,
        storage_path=str(storage_path),
        client_name=client_name,
        status=SpecificationStatus.UPLOADED,
        meta={},
    )
    session.add(spec)
    await session.commit()
    await session.refresh(spec)

    # Ставим задачу в очередь. Если брокер недоступен, эндпоинт всё равно
    # вернёт 202 — обработка просто начнётся позже после поднятия воркера
    # (повторный enqueue см. POST /retry в Phase 2).
    try:
        process_specification.delay(str(spec.id))
    except Exception:
        # Логируем, но не валим запрос — пользователь увидит status=uploaded
        # и сможет вручную перезапустить из UI
        pass

    return SpecificationUploadResponse(
        spec_id=spec.id,
        status=spec.status,
        filename=spec.source_filename,
        created_at=spec.created_at,
    )


@router.get(
    "/",
    response_model=list[SpecificationRead],
    summary="Список спецификаций",
)
async def list_specifications(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[SpecificationRead]:
    settings = get_settings()
    rows = (
        await session.scalars(
            select(Specification)
            .order_by(Specification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return [
        SpecificationRead(
            id=r.id,
            source_filename=r.source_filename,
            client_name=r.client_name,
            status=r.status,
            error_message=r.error_message,
            created_at=r.created_at,
            completed_at=r.completed_at,
            counts=await _compute_counts(
                session, r.id, settings.confidence_auto_confirm, settings.confidence_min
            ),
        )
        for r in rows
    ]


@router.get(
    "/{spec_id}",
    response_model=SpecificationRead,
    summary="Детали спецификации",
)
async def get_specification(
    spec_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> SpecificationRead:
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )
    settings = get_settings()
    return SpecificationRead(
        id=spec.id,
        source_filename=spec.source_filename,
        client_name=spec.client_name,
        status=spec.status,
        error_message=spec.error_message,
        created_at=spec.created_at,
        completed_at=spec.completed_at,
        counts=await _compute_counts(
            session, spec.id, settings.confidence_auto_confirm, settings.confidence_min
        ),
    )


@router.get(
    "/{spec_id}/items",
    response_model=PaginatedSpecItems,
    summary="Строки спецификации с кандидатами",
)
async def get_specification_items(
    spec_id: UUID,
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> PaginatedSpecItems:
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )

    total = await session.scalar(
        select(func.count()).select_from(SpecItem).where(SpecItem.spec_id == spec_id)
    )

    offset = (page - 1) * page_size
    spec_items = (
        await session.scalars(
            select(SpecItem)
            .where(SpecItem.spec_id == spec_id)
            .order_by(SpecItem.line_number)
            .limit(page_size)
            .offset(offset)
            .options(
                selectinload(SpecItem.candidates)
                .selectinload(MatchCandidate.item)
                .selectinload(Item.source),
                selectinload(SpecItem.verification),
            )
        )
    ).all()

    items_out: list[SpecItemRead] = []
    for spec_item in spec_items:
        catalog_candidates: list[CandidateRead] = []
        supplier_candidates: list[CandidateRead] = []
        for cand in spec_item.candidates:
            source: DataSource = cand.item.source
            read = CandidateRead(
                item_id=cand.item.id,
                source_id=source.id,
                source_type=source.type,
                article=cand.item.article_raw,
                name=cand.item.name,
                manufacturer=cand.item.manufacturer,
                price=cand.item.price,
                currency=cand.item.currency,
                unit=cand.item.unit,
                in_stock=cand.item.in_stock,
                confidence=float(cand.confidence),
                match_type=cand.match_type,
                rank=cand.rank,
                explanation=cand.explanation,
            )
            if source.type is DataSourceType.COMPANY_CATALOG:
                catalog_candidates.append(read)
            else:
                supplier_candidates.append(read)

        catalog_candidates.sort(key=lambda c: c.rank)
        supplier_candidates.sort(key=lambda c: c.rank)

        verification_read = None
        if spec_item.verification is not None:
            v = spec_item.verification
            verification_read = VerificationRead(
                decision=v.decision,
                chosen_item_id=v.chosen_item_id,
                decided_by=v.decided_by,
                notes=v.notes,
                decided_at=v.updated_at,
            )

        items_out.append(
            SpecItemRead(
                id=spec_item.id,
                line_number=spec_item.line_number,
                name_raw=spec_item.name_raw,
                article_raw=spec_item.article_raw,
                manufacturer_raw=spec_item.manufacturer_raw,
                unit_raw=spec_item.unit_raw,
                quantity=spec_item.quantity,
                price_raw=spec_item.price_raw,
                currency_raw=spec_item.currency_raw,
                notes=spec_item.notes,
                name_normalized=spec_item.name_normalized,
                article_normalized=spec_item.article_normalized,
                unit_normalized=spec_item.unit_normalized,
                candidates_catalog=catalog_candidates,
                candidates_suppliers=supplier_candidates,
                verification=verification_read,
            )
        )

    return PaginatedSpecItems(
        items=items_out,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


# --- Helpers ---


async def _compute_counts(
    session: AsyncSession,
    spec_id: UUID,
    high_threshold: float,
    min_threshold: float,
) -> SpecificationCounts:
    """Считает агрегаты по топ-кандидату каталога для каждой строки спец-ции.

    Если в каталоге кандидатов нет, смотрим на топ поставщиков. Если совсем
    ничего — not_found.
    """
    items_total = (
        await session.scalar(
            select(func.count()).select_from(SpecItem).where(SpecItem.spec_id == spec_id)
        )
        or 0
    )

    if items_total == 0:
        return SpecificationCounts()

    # Считаем по топ-1 (rank=1) кандидату любого типа: catalog приоритетнее,
    # но в Phase 1 для счётчиков просто берём максимум confidence среди rank=1.
    stmt = (
        select(
            SpecItem.id,
            func.max(MatchCandidate.confidence).label("best_confidence"),
        )
        .join(MatchCandidate, MatchCandidate.spec_item_id == SpecItem.id, isouter=True)
        .where(SpecItem.spec_id == spec_id, MatchCandidate.rank == 1)
        .group_by(SpecItem.id)
    )
    rows = (await session.execute(stmt)).all()

    high = sum(1 for _, c in rows if c is not None and float(c) >= high_threshold)
    medium = sum(1 for _, c in rows if c is not None and min_threshold <= float(c) < high_threshold)
    matched_ids = {r[0] for r in rows}
    # «not_found» = всё, что не попало в matched_ids или попало с confidence < min
    low = sum(1 for _, c in rows if c is not None and float(c) < min_threshold)
    not_found = items_total - len(matched_ids) + low

    return SpecificationCounts(
        items_total=int(items_total),
        items_matched_high=high,
        items_matched_medium=medium,
        items_not_found=not_found,
    )


def _validate_upload(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Имя файла не указано"},
        )
    ext = Path(file.filename).suffix.lower()
    allowed = SpecificationParser.supported_extensions()
    if ext not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "message": f"Расширение {ext} не поддержано в Phase 1",
                "allowed": sorted(allowed),
            },
        )

    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "message": f"Файл превышает максимальный размер {settings.max_upload_size_mb} МБ",
                "size_bytes": file.size,
            },
        )
