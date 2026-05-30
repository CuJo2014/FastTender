"""Поставщики и их прайсы (раздел 4.3, Приложение C.4)."""

import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.core.config import get_settings
from fasttender.core.db import get_session
from fasttender.models import DataSource, DataSourceType, Supplier
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
from fasttender.services.parser import SpecificationParser

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get(
    "/",
    response_model=list[SupplierRead],
    summary="Список поставщиков",
)
async def list_suppliers(
    session: AsyncSession = Depends(get_session),
) -> list[Supplier]:
    result = await session.scalars(select(Supplier).order_by(Supplier.name))
    return list(result.all())


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
    supplier = Supplier(
        name=payload.name,
        contact_email=payload.contact_email,
        prefix=payload.prefix,
        meta=payload.meta,
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
    for field_name, value in data.items():
        setattr(supplier, field_name, value)
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
