"""Каталог компании (раздел 4.3, Приложение C.4)."""

import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.core.config import get_settings
from fasttender.core.db import get_session
from fasttender.models import DataSource, DataSourceType, Item
from fasttender.services.importer import (
    CatalogImporter,
    ImportError,
    ImportMode,
    ImportReport,
)
from fasttender.services.parser import SpecificationParser

router = APIRouter(prefix="/catalog", tags=["catalog"])


class CatalogInfo(BaseModel):
    """Сводка по каталогу компании для UI."""

    items_count: int = 0
    last_synced_at: datetime | None = None
    created_at: datetime | None = None


@router.get(
    "/info",
    response_model=CatalogInfo,
    summary="Сводка по каталогу (счётчик позиций, дата последнего импорта)",
)
async def get_catalog_info(session: AsyncSession = Depends(get_session)) -> CatalogInfo:
    source = await session.scalar(
        select(DataSource).where(DataSource.type == DataSourceType.COMPANY_CATALOG)
    )
    if source is None:
        return CatalogInfo()
    items_count = await session.scalar(
        select(func.count(Item.id)).where(Item.source_id == source.id, Item.is_active.is_(True))
    )
    return CatalogInfo(
        items_count=int(items_count or 0),
        last_synced_at=source.last_synced_at,
        created_at=source.created_at,
    )


@router.post(
    "/import",
    response_model=ImportReport,
    status_code=status.HTTP_200_OK,
    summary="Импорт каталога компании из XLSX/CSV (Phase 1: синхронный)",
)
async def import_catalog(
    file: UploadFile = File(...),
    mode: ImportMode = Query(ImportMode.REPLACE),
    session: AsyncSession = Depends(get_session),
) -> ImportReport:
    """Загружает каталог компании.

    Phase 1: ответ синхронный, 30K строк bulk-insert укладывается в секунды.
    В Phase 2 при переходе на OpenSearch будем переводить в Celery-задачу
    с возвратом job_id (Приложение C.4).
    """
    _validate_upload(file)

    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=Path(file.filename or "catalog.xlsx").suffix,
        dir=settings.upload_dir,
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        shutil.copyfileobj(file.file, tmp)

    try:
        importer = CatalogImporter()
        try:
            report = await importer.import_file(session, tmp_path, mode=mode)
        except ImportError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": str(exc), "details": exc.details},
            ) from exc

        await session.commit()
        return report
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/search", summary="Поиск по каталогу (TODO Phase 1)")
async def search_catalog(q: str = "", limit: int = 20) -> dict[str, list]:
    return {"results": []}


# --- Helpers ---


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
