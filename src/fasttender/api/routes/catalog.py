"""Каталог компании (раздел 4.3, Приложение C.4)."""

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

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


class CatalogSearchResult(BaseModel):
    """Одна позиция в результате поиска по каталогу."""

    item_id: UUID
    code_1c: str | None = None
    article: str | None = None
    name: str
    manufacturer: str | None = None
    category_path: str | None = None
    price: float | None = None
    currency: str | None = None
    unit: str | None = None


@router.get(
    "/search",
    response_model=list[CatalogSearchResult],
    summary="Поиск по каталогу для ручного выбора менеджером",
)
async def search_catalog(
    q: str = Query("", description="Поиск по code_1c / артикулу / наименованию"),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[CatalogSearchResult]:
    """Используется когда менеджер знает что нужен конкретный товар
    каталога (Код 1С Ц0000001234) и хочет привязать его напрямую,
    минуя топ-5 кандидатов матчера.

    Стратегия поиска:
      1. Точное совпадение code_1c (case-sensitive) — top priority
      2. Точное совпадение article_normalized (uppercase)
      3. ILIKE по name — для поиска «по части имени»
    """
    query = q.strip()
    if not query:
        return []

    source_id = await session.scalar(
        select(DataSource.id).where(DataSource.type == DataSourceType.COMPANY_CATALOG)
    )
    if source_id is None:
        return []

    # Нормализуем запрос для article (как делает normalize_article: uppercase
    # без пробелов и дефисов)
    article_query = "".join(c for c in query.upper() if c.isalnum())

    # Один SELECT с условием OR: code_1c точное / article точное / name ILIKE.
    # ORDER BY дополнительно сортирует чтобы точные совпадения были выше.
    name_pattern = f"%{query}%"
    stmt = (
        select(Item)
        .where(
            Item.source_id == source_id,
            Item.is_active.is_(True),
            (Item.code_1c == query)
            | (Item.article_normalized == article_query)
            | Item.name.ilike(name_pattern),
        )
        .order_by(
            # Точные code_1c/article выше, потом по имени
            (Item.code_1c == query).desc(),
            (Item.article_normalized == article_query).desc(),
            Item.name,
        )
        .limit(limit)
    )
    rows = (await session.scalars(stmt)).all()

    return [
        CatalogSearchResult(
            item_id=item.id,
            code_1c=item.code_1c,
            article=item.article_raw,
            name=item.name,
            manufacturer=item.manufacturer,
            category_path=item.category_path,
            price=float(item.price) if item.price is not None else None,
            currency=item.currency,
            unit=item.unit,
        )
        for item in rows
    ]


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
