"""Импорт каталога компании (раздел 16.3 пункт 2, Приложение C.1).

Минимум для Фазы 1:
  - Парсинг файла через SpecificationParser (XLSX/CSV).
  - Маппинг строк в Item с привязкой к единственному DataSource
    типа COMPANY_CATALOG (создаётся лениво при первом импорте).
  - Нормализация артикула и наименования через value_normalizer.
  - Валидация: пустые имена и дубли артикулов внутри файла попадают в отчёт,
    импорт не падает.
  - Технические характеристики (Item.attributes) не извлекаются —
    остаются {}. Это Фаза 2 (см. раздел 4.2).

Общая логика (validate/dedupe/replace/merge) — в _base.py, чтобы переиспользовать
для импорта прайсов поставщиков (pricelist.py).
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import DataSource, DataSourceStatus, DataSourceType
from fasttender.services.importer._base import apply_to_source, validate_and_dedupe
from fasttender.services.importer.types import (
    ImportError,
    ImportMode,
    ImportReport,
)
from fasttender.services.parser import ParseError, SpecificationParser

DEFAULT_CATALOG_NAME = "Каталог компании"


class CatalogImporter:
    """Импортирует каталог компании из файла Excel/CSV.

    Использование:

        importer = CatalogImporter()
        async with session_factory() as session:
            report = await importer.import_file(
                session, Path("catalog.xlsx"), mode=ImportMode.REPLACE,
            )
            await session.commit()
    """

    def __init__(self, parser: SpecificationParser | None = None) -> None:
        self._parser = parser or SpecificationParser()

    async def import_file(
        self,
        session: AsyncSession,
        path: Path,
        *,
        mode: ImportMode = ImportMode.REPLACE,
        catalog_name: str | None = None,
    ) -> ImportReport:
        """Парсит файл и применяет к каталогу компании.

        Не выполняет commit — это ответственность вызывающего кода
        (FastAPI endpoint / Celery task), чтобы можно было откатить
        весь импорт при ошибке выше по стеку.
        """
        try:
            parse_result = self._parser.parse(path)
        except ParseError as exc:
            raise ImportError(
                f"Не удалось распарсить каталог: {exc}",
                details=exc.details,
            ) from exc

        source = await self._get_or_create_catalog_source(
            session, name=catalog_name or DEFAULT_CATALOG_NAME
        )

        report = ImportReport(
            source_id=str(source.id),
            source_name=source.name,
            mode=mode,
            rows_total=len(parse_result.items),
        )

        valid_items = validate_and_dedupe(parse_result.items, report)
        await apply_to_source(session, source, valid_items, mode, report)
        return report

    @staticmethod
    async def _get_or_create_catalog_source(session: AsyncSession, *, name: str) -> DataSource:
        """Лениво создаёт единственный источник типа COMPANY_CATALOG.

        В Фазе 1 — одна установка = одна компания (раздел 5.5), значит
        каталог тоже один. В Фазе 2 при появлении multi-tenancy этот
        запрос будет фильтроваться ещё и по tenant_id.
        """
        stmt = select(DataSource).where(DataSource.type == DataSourceType.COMPANY_CATALOG)
        existing = await session.scalar(stmt)
        if existing is not None:
            return existing

        source = DataSource(
            type=DataSourceType.COMPANY_CATALOG,
            name=name,
            status=DataSourceStatus.ACTIVE,
            config={},
        )
        session.add(source)
        await session.flush()  # нужен source.id для последующих вставок
        return source
