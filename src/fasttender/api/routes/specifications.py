"""Спецификации (раздел 4, Приложение C.4).

Phase 1:
  POST /specifications/                                 — загрузка файла, 202 + spec_id
  GET  /specifications/                                 — список с агрегатами
  GET  /specifications/{id}                             — статус + счётчики
  GET  /specifications/{id}/items                       — строки с кандидатами
  POST /specifications/{id}/items/{spec_item_id}/verify — решение по строке
  POST /specifications/{id}/auto-confirm                — массовое авто-подтверждение
  GET  /specifications/{id}/export                      — выгрузка XLSX/CSV

Реальная обработка — в Celery-задаче `fasttender.process_specification`,
которая дёргается из POST. Если воркер недоступен — спец останется в
статусе uploaded до запуска воркера.
"""

import shutil
import tempfile
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func, nullslast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fasttender.core.config import get_settings
from fasttender.core.db import get_session
from fasttender.models import (
    Client,
    DataSource,
    DataSourceType,
    Item,
    MatchCandidate,
    Specification,
    SpecificationStatus,
    SpecItem,
    TradingPlatform,
    Verification,
    VerificationDecision,
)
from fasttender.schemas.specification import (
    CandidateRead,
    ChosenItemRead,
    LinkedCatalogItemRead,
    PaginatedSpecItems,
    SpecificationCounts,
    SpecificationRead,
    SpecificationUpdate,
    SpecificationUploadResponse,
    SpecItemRead,
    VerificationRead,
)
from fasttender.schemas.verification import (
    AutoConfirmRequest,
    AutoConfirmResponse,
    BulkVerifyRequest,
    BulkVerifyResponse,
    VerifyRequest,
    VerifyResponse,
)
from fasttender.services.export import ExportFormat, build_export
from fasttender.services.parser import SpecificationParser
from fasttender.services.verification import VerificationError, VerificationService
from fasttender.tasks.process import process_specification
from fasttender.tasks.process import rematch_specification as rematch_task

router = APIRouter(prefix="/specifications", tags=["specifications"])


@router.post(
    "/",
    response_model=SpecificationUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Загрузка спецификации",
)
async def upload_specification(
    file: UploadFile = File(...),
    client_id: UUID | None = Query(None, description="Клиент из справочника (приоритетнее имени)"),
    client_name: str | None = Query(None, max_length=255),
    session: AsyncSession = Depends(get_session),
) -> SpecificationUploadResponse:
    _validate_upload(file)

    # Клиент из справочника приоритетнее свободного имени: привязываем по FK
    # и денормализуем имя (для legacy/аудита/экспорта).
    resolved_client_id: UUID | None = None
    resolved_client_name: str | None = client_name
    if client_id is not None:
        client = await session.get(Client, client_id)
        if client is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Клиент не найден"},
            )
        resolved_client_id = client.id
        resolved_client_name = client.name

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
        client_id=resolved_client_id,
        client_name=resolved_client_name,
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
        async_result = process_specification.delay(str(spec.id))
        # Сохраняем Celery task_id — нужен для прерывания обработки (POST /abort).
        spec.meta = {**(spec.meta or {}), "task_id": async_result.id}
        await session.commit()
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
    rows = (
        await session.scalars(
            select(Specification)
            .order_by(Specification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return [await _spec_read(session, r) for r in rows]


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
    return await _spec_read(session, spec)


@router.delete(
    "/{spec_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить спецификацию (строки, кандидаты, верификации — каскадно)",
)
async def delete_specification(
    spec_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Полное удаление спецификации.

    Каскадно (FK ondelete=CASCADE) удаляются spec_item → match_candidate,
    verification. Позиции каталога/прайсов (Item) НЕ затрагиваются — на них
    лишь ссылались кандидаты. Загруженный файл удаляется best-effort.
    """
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )
    storage_path = spec.storage_path
    await session.delete(spec)
    await session.commit()
    # Удаляем исходный файл, если ещё лежит в upload-каталоге
    if storage_path:
        with suppress(OSError):
            Path(storage_path).unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{spec_id}",
    response_model=SpecificationRead,
    summary="Изменить спецификацию (привязка к клиенту)",
)
async def update_specification(
    spec_id: UUID,
    payload: SpecificationUpdate,
    session: AsyncSession = Depends(get_session),
) -> SpecificationRead:
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )
    data = payload.model_dump(exclude_unset=True)
    if "client_id" in data:
        cid = data["client_id"]
        if cid is not None:
            client = await session.get(Client, cid)
            if client is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"message": "Клиент не найден"},
                )
            spec.client_id = cid
            spec.client_name = client.name  # денормализуем для списка/экспорта
        else:
            spec.client_id = None
    if "client_name" in data:
        spec.client_name = data["client_name"]
    # Флаг «Спецификация ТП»: снятие — скрыть и очистить площадку
    if "is_tp" in data:
        if data["is_tp"]:
            spec.is_tp = True
        else:
            spec.is_tp = False
            spec.trading_platform_id = None
            spec.trading_platform = None
    # Выбор площадки из справочника
    if "trading_platform_id" in data:
        pid = data["trading_platform_id"]
        if pid is not None:
            platform = await session.get(TradingPlatform, pid)
            if platform is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"message": "Площадка не найдена"},
                )
            spec.trading_platform_id = pid
            spec.trading_platform = platform.name  # денорм-имя для экспорта
            spec.is_tp = True
        else:
            spec.trading_platform_id = None
            spec.trading_platform = None
    # Прочие реквизиты тендера
    for field in ("spec_number", "spec_date", "delivery_date"):
        if field in data:
            setattr(spec, field, data[field])
    await session.commit()
    await session.refresh(spec)
    return await _spec_read(session, spec)


class ItemStatusFilter(StrEnum):
    """Сегменты таблицы строк (ось состояния, Design lock ревизии).

    `pending`/`confirmed`/`rejected` — ось решения менеджера;
    `no_candidate` — ось качества (у строки нет ни одного кандидата),
    показывается независимо от решения.
    """

    all = "all"
    pending = "pending"
    confirmed = "confirmed"
    rejected = "rejected"
    no_candidate = "no_candidate"


class ItemSort(StrEnum):
    line_number = "line_number"
    confidence_desc = "confidence_desc"
    confidence_asc = "confidence_asc"


def _item_status_conditions(status_filter: ItemStatusFilter) -> list:  # type: ignore[type-arg]
    """WHERE-условия для сегментного фильтра (применяются и к count, и к выборке)."""
    if status_filter is ItemStatusFilter.pending:
        return [~exists().where(Verification.spec_item_id == SpecItem.id)]
    if status_filter is ItemStatusFilter.confirmed:
        return [
            exists().where(
                and_(
                    Verification.spec_item_id == SpecItem.id,
                    Verification.decision == VerificationDecision.CONFIRMED,
                )
            )
        ]
    if status_filter is ItemStatusFilter.rejected:
        return [
            exists().where(
                and_(
                    Verification.spec_item_id == SpecItem.id,
                    Verification.decision == VerificationDecision.REJECTED,
                )
            )
        ]
    if status_filter is ItemStatusFilter.no_candidate:
        return [~exists().where(MatchCandidate.spec_item_id == SpecItem.id)]
    return []


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
    status_filter: ItemStatusFilter = Query(ItemStatusFilter.all, alias="status"),
    sort: ItemSort = Query(ItemSort.line_number),
) -> PaginatedSpecItems:
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )

    # Один набор условий — и для total, и для выборки (иначе пагинация врёт).
    base_where = [SpecItem.spec_id == spec_id, *_item_status_conditions(status_filter)]

    total = await session.scalar(
        select(func.count()).select_from(SpecItem).where(*base_where)
    )

    offset = (page - 1) * page_size
    data_q = select(SpecItem).where(*base_where)
    if sort is ItemSort.line_number:
        data_q = data_q.order_by(SpecItem.line_number)
    else:
        # Сортировка по уверенности топ-1 кандидата; строки без кандидата
        # (NULL) — всегда в конце, для них есть отдельный сегмент.
        best_conf = (
            select(
                MatchCandidate.spec_item_id.label("sid"),
                func.max(MatchCandidate.confidence).label("best"),
            )
            .where(MatchCandidate.rank == 1)
            .group_by(MatchCandidate.spec_item_id)
            .subquery()
        )
        best = best_conf.c.best
        data_q = data_q.outerjoin(best_conf, best_conf.c.sid == SpecItem.id).order_by(
            nullslast(best.desc() if sort is ItemSort.confidence_desc else best.asc()),
            SpecItem.line_number,
        )

    spec_items = (
        await session.scalars(
            data_q.limit(page_size)
            .offset(offset)
            .options(
                selectinload(SpecItem.candidates)
                .selectinload(MatchCandidate.item)
                .selectinload(Item.source),
                # Без joinedload каталог-карточка будет N+1 запросом
                selectinload(SpecItem.candidates)
                .selectinload(MatchCandidate.item)
                .joinedload(Item.linked_catalog_item),
                selectinload(SpecItem.verification),
            )
        )
    ).all()

    # Выбранные позиции (chosen_item) — в т.ч. найденные через поиск, которых
    # нет среди топ-кандидатов. Один батч-запрос на страницу, чтобы UI показал
    # именно выбранную позицию в колонке «Выбранная позиция».
    chosen_ids = {
        si.verification.chosen_item_id
        for si in spec_items
        if si.verification is not None and si.verification.chosen_item_id is not None
    }
    chosen_items: dict[UUID, Item] = {}
    if chosen_ids:
        chosen_rows = await session.scalars(
            select(Item).where(Item.id.in_(chosen_ids)).options(joinedload(Item.source))
        )
        chosen_items = {it.id: it for it in chosen_rows}

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
                code_1c=cand.item.code_1c,
                supplier_sku=cand.item.supplier_sku,
                linked_catalog=_build_linked_catalog(cand.item),
                catalog_link_source=cand.item.catalog_link_source,
                name=cand.item.name,
                manufacturer=cand.item.manufacturer,
                category_path=cand.item.category_path,
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
            chosen_read: ChosenItemRead | None = None
            if v.chosen_item_id is not None:
                ci = chosen_items.get(v.chosen_item_id)
                if ci is not None:
                    chosen_read = ChosenItemRead(
                        item_id=ci.id,
                        source_type=ci.source.type if ci.source else None,
                        article=ci.article_raw,
                        name=ci.name,
                        manufacturer=ci.manufacturer,
                        price=ci.price,
                        currency=ci.currency,
                    )
            verification_read = VerificationRead(
                decision=v.decision,
                chosen_item_id=v.chosen_item_id,
                chosen_item=chosen_read,
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
                attributes_raw=spec_item.attributes_raw,
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


# --- Верификация (раздел 4.7) ---


@router.post(
    "/{spec_id}/items/{spec_item_id}/verify",
    response_model=VerifyResponse,
    summary="Решение менеджера по строке",
)
async def verify_spec_item(
    spec_id: UUID,
    spec_item_id: UUID,
    payload: VerifyRequest,
    session: AsyncSession = Depends(get_session),
) -> VerifyResponse:
    service = VerificationService(session)
    try:
        verification = await service.upsert(
            spec_id=spec_id,
            spec_item_id=spec_item_id,
            decision=payload.decision,
            chosen_item_id=payload.chosen_item_id,
            notes=payload.notes,
            decided_by=payload.decided_by,
        )
    except VerificationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": str(exc)},
        ) from exc

    await session.commit()
    await session.refresh(verification)

    # Auto-promote: если все строки спеки получили verification — статус
    # переключается на VERIFIED (UX-фидбэк 1 июня 2026).
    await _auto_promote_to_verified(session, spec_id)
    await session.commit()

    return VerifyResponse(
        spec_item_id=verification.spec_item_id,
        decision=verification.decision,
        chosen_item_id=verification.chosen_item_id,
        decided_by=verification.decided_by,
        notes=verification.notes,
        decided_at=verification.updated_at,
    )


@router.delete(
    "/{spec_id}/items/{spec_item_id}/verify",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отказаться от сопоставления строки (откат верификации)",
)
async def unverify_spec_item(
    spec_id: UUID,
    spec_item_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Удаляет решение по строке — возвращает её в «не верифицировано»
    (менеджер ошибся). Если спека была VERIFIED — статус снова REVIEWING."""
    service = VerificationService(session)
    try:
        await service.delete(spec_id=spec_id, spec_item_id=spec_item_id)
    except VerificationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": str(exc)},
        ) from exc
    # Демоут: спека больше не полностью верифицирована
    spec = await session.get(Specification, spec_id)
    if spec is not None and spec.status is SpecificationStatus.VERIFIED:
        spec.status = SpecificationStatus.REVIEWING
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _auto_promote_to_verified(session: AsyncSession, spec_id: UUID) -> None:
    """Если все spec_item имеют Verification — статус спеки → VERIFIED."""
    spec = await session.get(Specification, spec_id)
    if spec is None or spec.status in (
        SpecificationStatus.VERIFIED,
        SpecificationStatus.EXPORTED,
        SpecificationStatus.CANCELLED,
    ):
        return
    total = await session.scalar(
        select(func.count()).select_from(SpecItem).where(SpecItem.spec_id == spec_id)
    )
    verified = await session.scalar(
        select(func.count())
        .select_from(Verification)
        .join(SpecItem, SpecItem.id == Verification.spec_item_id)
        .where(SpecItem.spec_id == spec_id)
    )
    if total and verified and int(verified) >= int(total):
        spec.status = SpecificationStatus.VERIFIED


class CancelRequest(BaseModel):
    """Тело POST /specifications/{id}/cancel."""

    reason: str | None = Field(None, max_length=1024)


@router.post(
    "/{spec_id}/cancel",
    response_model=SpecificationRead,
    summary="Отменить спецификацию (отказ от поставки)",
)
async def cancel_specification(
    spec_id: UUID,
    payload: CancelRequest,
    session: AsyncSession = Depends(get_session),
) -> SpecificationRead:
    """Менеджер отказывается обеспечивать поставку по этой спецификации.

    Статус → CANCELLED, причина (если указана) пишется в error_message
    (переиспользуем поле, чтобы не плодить сущности).
    """
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )
    spec.status = SpecificationStatus.CANCELLED
    if payload.reason:
        spec.error_message = f"Отказ: {payload.reason}"
    else:
        spec.error_message = "Отказ от поставки"
    await session.commit()
    await session.refresh(spec)
    counts = await _compute_counts(session, spec.id)
    return SpecificationRead.model_validate({**spec.__dict__, "counts": counts})


_IN_PROGRESS_STATUSES = frozenset(
    {
        SpecificationStatus.UPLOADED,
        SpecificationStatus.PARSING,
        SpecificationStatus.PARSED,
        SpecificationStatus.MATCHING,
    }
)


@router.post(
    "/{spec_id}/abort",
    response_model=SpecificationRead,
    summary="Прервать обработку (остановить парсинг/матчинг)",
)
async def abort_specification(
    spec_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> SpecificationRead:
    """Останавливает фоновую Celery-задачу и помечает спеку прерванной.

    В отличие от /cancel (бизнес-отказ от поставки) — именно прекращает
    работу парсера/матчера. Частичные результаты, уже закоммиченные
    батчами, остаются (миграция 0015).
    """
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )
    if spec.status not in _IN_PROGRESS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Спецификация не в обработке — прерывать нечего"},
        )

    task_id = (spec.meta or {}).get("task_id")
    if task_id:
        try:
            from fasttender.core.celery_app import celery_app

            # terminate=True шлёт SIGTERM воркер-процессу задачи (prefork
            # переживёт). Брокер недоступен → graceful: статус всё равно ставим.
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        except Exception:
            pass

    spec.status = SpecificationStatus.CANCELLED
    spec.error_message = "Обработка прервана пользователем"
    await session.commit()
    await session.refresh(spec)
    return await _spec_read(session, spec)


@router.post(
    "/{spec_id}/rematch",
    response_model=SpecificationRead,
    summary="Повторный матчинг строк, которые ещё не подтверждены",
)
async def rematch_specification(
    spec_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> SpecificationRead:
    """Перезапускает матчинг ТОЛЬКО для не подтверждённых строк.

    Парсинг не выполняется. Строки с решением `confirmed` остаются как есть;
    у остальных кандидаты пересобираются заново, а прежнее неподтверждённое
    решение (`rejected`/`not_found`/`new_item_requested`) сбрасывается.
    Полезно, когда каталог/прайсы пополнили и нужно переподобрать остаток.
    """
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )
    if spec.status in _IN_PROGRESS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Спецификация уже в обработке"},
        )
    items_total = await session.scalar(
        select(func.count())
        .select_from(SpecItem)
        .where(SpecItem.spec_id == spec_id)
    )
    if not items_total:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Нет распарсенных строк — матчить нечего"},
        )

    # Ставим задачу ДО смены статуса: если брокер недоступен — спека остаётся
    # в текущем статусе, а пользователь получит понятную ошибку.
    try:
        async_result = rematch_task.delay(str(spec.id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Очередь задач недоступна, попробуйте позже"},
        ) from exc

    spec.meta = {**(spec.meta or {}), "task_id": async_result.id}
    spec.status = SpecificationStatus.MATCHING
    spec.matched_count = 0
    spec.error_message = None
    await session.commit()
    await session.refresh(spec)
    return await _spec_read(session, spec)


@router.post(
    "/{spec_id}/auto-confirm",
    response_model=AutoConfirmResponse,
    summary="Массовое авто-подтверждение всех строк с confidence ≥ порога",
)
async def auto_confirm_specification(
    spec_id: UUID,
    payload: AutoConfirmRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> AutoConfirmResponse:
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )

    settings = get_settings()
    payload = payload or AutoConfirmRequest()
    threshold = (
        payload.min_confidence
        if payload.min_confidence is not None
        else settings.confidence_auto_confirm
    )

    service = VerificationService(session)
    if payload.dry_run:
        # Только счётчик «Авто-подтвердить (N)» — ничего не пишем и не коммитим.
        confirmed, skipped_existing, skipped_low = (
            await service.count_auto_confirm_targets(
                spec_id=spec_id,
                min_confidence=threshold,
                only_unverified=payload.only_unverified,
            )
        )
        return AutoConfirmResponse(
            confirmed_count=confirmed,
            skipped_already_verified=skipped_existing,
            skipped_below_threshold=skipped_low,
            threshold_used=threshold,
        )

    confirmed, skipped_existing, skipped_low = await service.auto_confirm(
        spec_id=spec_id,
        min_confidence=threshold,
        decided_by=payload.decided_by,
        only_unverified=payload.only_unverified,
    )
    await session.commit()
    # Все строки получили решение → статус VERIFIED (как в одиночном verify).
    await _auto_promote_to_verified(session, spec_id)
    await session.commit()

    return AutoConfirmResponse(
        confirmed_count=confirmed,
        skipped_already_verified=skipped_existing,
        skipped_below_threshold=skipped_low,
        threshold_used=threshold,
    )


@router.post(
    "/{spec_id}/items/bulk-verify",
    response_model=BulkVerifyResponse,
    summary="Массовое решение по выбранным строкам",
)
async def bulk_verify_items(
    spec_id: UUID,
    payload: BulkVerifyRequest,
    session: AsyncSession = Depends(get_session),
) -> BulkVerifyResponse:
    """Применяет решение к набору строк (чекбоксы в UI).

    CONFIRMED подтверждает топ-кандидата каждой строки; строки без кандидата
    пропускаются. Прочие решения применяются ко всем выбранным.
    """
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )

    service = VerificationService(session)
    try:
        applied, skipped_no_candidate = await service.bulk_verify(
            spec_id=spec_id,
            spec_item_ids=payload.item_ids,
            decision=payload.decision,
            decided_by=payload.decided_by,
        )
    except VerificationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": str(exc)},
        ) from exc

    await session.commit()
    await _auto_promote_to_verified(session, spec_id)
    await session.commit()

    return BulkVerifyResponse(
        applied=applied,
        skipped_no_candidate=skipped_no_candidate,
    )


# --- Экспорт (раздел 4.8) ---


@router.get(
    "/{spec_id}/export",
    summary="Выгрузка результатов в XLSX или CSV",
)
async def export_specification(
    spec_id: UUID,
    fmt: ExportFormat = Query(ExportFormat.XLSX, alias="format"),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    spec = await session.get(Specification, spec_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Спецификация не найдена"},
        )

    content, content_type, filename = await build_export(session, spec, fmt)

    return StreamingResponse(
        iter([content]),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
        },
    )


# --- Helpers ---


async def _spec_read(session: AsyncSession, spec: Specification) -> SpecificationRead:
    """Specification ORM → SpecificationRead (+ counts). Через model_validate,
    чтобы новые колонки (клиент, реквизиты) подхватывались автоматически."""
    settings = get_settings()
    counts = await _compute_counts(
        session, spec.id, settings.confidence_auto_confirm, settings.confidence_min
    )
    return SpecificationRead.model_validate({**spec.__dict__, "counts": counts})


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
    # Разносим «нет кандидата» и «слабый кандидат» (ось качества из ревизии UI):
    #   low          — кандидат есть (rank=1), но confidence < min
    #   no_candidate — у строки нет ни одного кандидата
    #   not_found    — сумма обоих (обратная совместимость со списком спек)
    low = sum(1 for _, c in rows if c is not None and float(c) < min_threshold)
    no_candidate = items_total - len(matched_ids)
    not_found = no_candidate + low

    # Разбивка по решению менеджера: verified = сумма всех решений; отдельно
    # confirmed/rejected — для чисел на сегментах фильтра таблицы.
    decision_rows = await session.execute(
        select(Verification.decision, func.count())
        .join(SpecItem, SpecItem.id == Verification.spec_item_id)
        .where(SpecItem.spec_id == spec_id)
        .group_by(Verification.decision)
    )
    by_decision = {d: int(c) for d, c in decision_rows}
    items_verified = sum(by_decision.values())
    confirmed = by_decision.get(VerificationDecision.CONFIRMED, 0)
    rejected = by_decision.get(VerificationDecision.REJECTED, 0)

    return SpecificationCounts(
        items_total=int(items_total),
        items_matched_high=high,
        items_matched_medium=medium,
        items_not_found=not_found,
        items_low=low,
        items_no_candidate=no_candidate,
        items_verified=items_verified,
        items_pending=int(items_total) - items_verified,
        items_confirmed=confirmed,
        items_rejected=rejected,
    )


def _build_linked_catalog(item: Item) -> LinkedCatalogItemRead | None:
    """Снимок каталог-карточки для CandidateRead.linked_catalog."""
    cat = item.linked_catalog_item
    if cat is None:
        return None
    return LinkedCatalogItemRead(
        item_id=cat.id,
        code_1c=cat.code_1c,
        article=cat.article_raw,
        name=cat.name,
        manufacturer=cat.manufacturer,
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
