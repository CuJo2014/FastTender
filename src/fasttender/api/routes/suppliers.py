"""Поставщики и их прайсы (раздел 4.3, Приложение C.4)."""

import shutil
import tempfile
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.core.config import get_settings
from fasttender.core.db import get_session
from fasttender.models import DataSource, DataSourceType, Item, Supplier
from fasttender.schemas.supplier import (
    PricelistSourceRead,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
)
from fasttender.services.importer import (
    ImportError,
    ImportMode,
    ImportReport,
    PriceListImporter,
)
from fasttender.services.importer._base import (
    apply_manufacturer_to_existing,
    auto_link_to_catalog,
    backfill_supplier_skus,
)
from fasttender.services.importer.transformations import (
    SupplierTransformations,
    apply_transformations,
)
from fasttender.services.parser import ParsedItem, SpecificationParser

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get(
    "/",
    response_model=list[SupplierRead],
    summary="Список поставщиков",
)
async def list_suppliers(
    session: AsyncSession = Depends(get_session),
) -> list[SupplierRead]:
    """Возвращает поставщиков с инфой о последнем импорте прайса и счётчиком позиций.

    UI использует pricelist_last_synced_at для отображения «Обновлён: дата»
    и items_count для бэйджа в свёрнутом виде.
    """
    suppliers = list((await session.scalars(select(Supplier).order_by(Supplier.name))).all())

    # Один запрос на все pricelist-источники + count активных позиций
    rows = (
        await session.execute(
            select(
                DataSource.supplier_id,
                DataSource.last_synced_at,
                func.count(Item.id).filter(Item.is_active.is_(True)).label("items"),
            )
            .outerjoin(Item, Item.source_id == DataSource.id)
            .where(DataSource.type == DataSourceType.SUPPLIER_PRICELIST)
            .group_by(DataSource.supplier_id, DataSource.last_synced_at)
        )
    ).all()
    by_supplier = {r.supplier_id: (r.last_synced_at, r.items) for r in rows}

    out: list[SupplierRead] = []
    for sup in suppliers:
        synced_at, items = by_supplier.get(sup.id, (None, 0))
        read = SupplierRead.model_validate(sup)
        read.pricelist_last_synced_at = synced_at
        read.pricelist_items_count = items or 0
        out.append(read)
    return out


@router.post(
    "/",
    response_model=SupplierRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать поставщика",
)
async def create_supplier(
    payload: SupplierCreate,
    session: AsyncSession = Depends(get_session),
) -> Supplier:
    meta = dict(payload.meta)
    if payload.transformations is not None:
        meta["transformations"] = payload.transformations.model_dump(exclude_none=True)
    supplier = Supplier(
        name=payload.name,
        contact_email=payload.contact_email,
        prefix=payload.prefix,
        meta=meta,
    )
    session.add(supplier)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        message = str(exc.orig) if exc.orig is not None else str(exc)
        if "ux_supplier_prefix" in message:
            detail = "Префикс уже используется другим поставщиком"
        else:
            detail = "Поставщик с таким именем уже существует"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": detail},
        ) from exc
    await session.refresh(supplier)
    return supplier


@router.patch(
    "/{supplier_id}",
    response_model=SupplierRead,
    summary="Обновить поставщика (имя, email, префикс)",
)
async def update_supplier(
    supplier_id: UUID,
    payload: SupplierUpdate,
    session: AsyncSession = Depends(get_session),
) -> Supplier:
    supplier = await session.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Поставщик не найден"},
        )
    data = payload.model_dump(exclude_unset=True)
    prefix_changed = "prefix" in data and data["prefix"] != supplier.prefix

    # Запоминаем старый manufacturer (если был) чтобы определить смену
    old_meta_transforms = (supplier.meta or {}).get("transformations") or {}
    old_manufacturer = old_meta_transforms.get("manufacturer")

    # transformations едет отдельно — сохраняем в meta
    new_manufacturer: str | None = None
    manufacturer_changed = False
    if "transformations" in data:
        new_meta = dict(supplier.meta) if supplier.meta else {}
        if data["transformations"] is None:
            new_meta.pop("transformations", None)
        else:
            # data["transformations"] уже dict после model_dump
            new_meta["transformations"] = {
                k: v for k, v in data["transformations"].items() if v is not None
            }
            new_manufacturer = new_meta["transformations"].get("manufacturer")
        supplier.meta = new_meta
        manufacturer_changed = new_manufacturer != old_manufacturer
        data.pop("transformations")

    for field_name, value in data.items():
        setattr(supplier, field_name, value)

    # Если впервые установили (или сменили) префикс — backfill SKU
    # существующим позициям прайсов поставщика
    if prefix_changed and supplier.prefix:
        await backfill_supplier_skus(session, supplier.id, supplier.prefix)

    # Если задан/сменён принудительный производитель — апдейтим существующие
    # позиции прайса немедленно (без re-import) + переcчитываем catalog-link
    if manufacturer_changed and new_manufacturer:
        await apply_manufacturer_to_existing(session, supplier.id, new_manufacturer)
        # Catalog-link зависит от manufacturer (article+brand match) → пере-расчёт
        source_ids = (
            await session.scalars(
                select(DataSource.id).where(
                    DataSource.supplier_id == supplier.id,
                    DataSource.type == DataSourceType.SUPPLIER_PRICELIST,
                )
            )
        ).all()
        for sid in source_ids:
            await auto_link_to_catalog(session, sid)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        message = str(exc.orig) if exc.orig is not None else str(exc)
        if "ux_supplier_prefix" in message:
            detail = "Префикс уже используется другим поставщиком"
        else:
            detail = "Поставщик с таким именем уже существует"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": detail},
        ) from exc
    await session.refresh(supplier)
    return supplier


@router.get(
    "/{supplier_id}",
    response_model=SupplierRead,
    summary="Детали поставщика",
)
async def get_supplier(
    supplier_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Supplier:
    supplier = await session.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Поставщик не найден"},
        )
    return supplier


@router.get(
    "/{supplier_id}/pricelist",
    response_model=PricelistSourceRead | None,
    summary="Получить источник прайса поставщика (один в Phase 1)",
)
async def get_supplier_pricelist(
    supplier_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DataSource | None:
    supplier = await session.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Поставщик не найден"},
        )
    return await session.scalar(
        select(DataSource).where(
            DataSource.type == DataSourceType.SUPPLIER_PRICELIST,
            DataSource.supplier_id == supplier_id,
        )
    )


@router.post(
    "/{supplier_id}/pricelists/import",
    response_model=ImportReport,
    status_code=status.HTTP_200_OK,
    summary="Импорт прайса поставщика из XLSX/CSV (Phase 1: синхронный)",
)
async def import_pricelist(
    supplier_id: UUID,
    file: UploadFile = File(...),
    mode: ImportMode = Query(ImportMode.REPLACE),
    sheet_name: str | None = Query(None, description="Имя листа Excel (опционально)"),
    session: AsyncSession = Depends(get_session),
) -> ImportReport:
    _validate_upload(file)

    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=Path(file.filename or "pricelist.xlsx").suffix,
        dir=settings.upload_dir,
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        shutil.copyfileobj(file.file, tmp)

    try:
        importer = PriceListImporter()
        try:
            report = await importer.import_file(
                session,
                supplier_id=supplier_id,
                path=tmp_path,
                mode=mode,
                sheet_name=sheet_name,
            )
        except ImportError as exc:
            await session.rollback()
            status_code = (
                status.HTTP_404_NOT_FOUND
                if "не найден" in str(exc)
                else status.HTTP_422_UNPROCESSABLE_ENTITY
            )
            raise HTTPException(
                status_code=status_code,
                detail={"message": str(exc), "details": exc.details},
            ) from exc

        await session.commit()
        return report
    finally:
        tmp_path.unlink(missing_ok=True)


# --- Helpers (дублирует логику из catalog.py — выносить в общий модуль пока рано) ---


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


# --- P3.7: preview эффекта трансформаций на образце строки ---


class TransformPreviewRequest(BaseModel):
    transformations: SupplierTransformations
    name: str = Field(..., min_length=1)
    price: Decimal | None = None
    unit: str | None = None
    currency: str | None = None
    manufacturer: str | None = None


class TransformPreviewResponse(BaseModel):
    name: str
    manufacturer: str | None = None
    price: Decimal | None = None
    unit: str | None = None
    currency: str | None = None


@router.post(
    "/preview-transform",
    response_model=TransformPreviewResponse,
    summary="Применить трансформации к образцу строки (preview, без БД)",
)
async def preview_transform(payload: TransformPreviewRequest) -> TransformPreviewResponse:
    """Показывает, во что превратится строка прайса при заданных трансформациях.

    Чистая функция — БД не трогает. Для UI-настройки brand_regex/НДС/дефолтов.
    """
    item = ParsedItem(
        line_number=1,
        name=payload.name,
        price=payload.price,
        unit=payload.unit,
        currency=payload.currency,
        manufacturer=payload.manufacturer,
    )
    out = apply_transformations([item], payload.transformations)[0]
    return TransformPreviewResponse(
        name=out.name,
        manufacturer=out.manufacturer,
        price=out.price,
        unit=out.unit,
        currency=out.currency,
    )


# --- P3.8: экспорт/импорт настроек поставщиков ---


class SupplierSettings(BaseModel):
    name: str
    prefix: str | None = None
    transformations: dict | None = None


class SettingsImportResult(BaseModel):
    applied: int
    skipped_unknown: list[str]


@router.get(
    "/settings/export",
    response_model=list[SupplierSettings],
    summary="Экспорт настроек всех поставщиков (имя, префикс, трансформации)",
)
async def export_supplier_settings(
    session: AsyncSession = Depends(get_session),
) -> list[SupplierSettings]:
    suppliers = list((await session.scalars(select(Supplier).order_by(Supplier.name))).all())
    return [
        SupplierSettings(
            name=s.name,
            prefix=s.prefix,
            transformations=(s.meta or {}).get("transformations"),
        )
        for s in suppliers
    ]


@router.post(
    "/settings/import",
    response_model=SettingsImportResult,
    summary="Импорт настроек (по имени; обновляет существующих, не создаёт)",
)
async def import_supplier_settings(
    payload: list[SupplierSettings],
    session: AsyncSession = Depends(get_session),
) -> SettingsImportResult:
    """Применяет настройки к СУЩЕСТВУЮЩИМ поставщикам (матч по имени).

    Обновляет prefix и transformations. Неизвестные имена — в skipped (не
    создаём: создание требует прайса/контактов отдельно). Массовый ре-импорт
    прайсов невозможен — исходные файлы не хранятся.
    """
    by_name = {
        s.name: s for s in (await session.scalars(select(Supplier))).all()
    }
    applied = 0
    skipped: list[str] = []
    for entry in payload:
        sup = by_name.get(entry.name)
        if sup is None:
            skipped.append(entry.name)
            continue
        new_meta = dict(sup.meta or {})
        if entry.transformations:
            # валидируем через схему, отбрасывая мусор
            new_meta["transformations"] = SupplierTransformations.model_validate(
                entry.transformations
            ).model_dump(exclude_none=True)
        else:
            new_meta.pop("transformations", None)
        sup.meta = new_meta
        prefix_changed = entry.prefix != sup.prefix
        sup.prefix = entry.prefix
        if prefix_changed and sup.prefix:
            await backfill_supplier_skus(session, sup.id, sup.prefix)
        applied += 1
    await session.commit()
    return SettingsImportResult(applied=applied, skipped_unknown=skipped)
