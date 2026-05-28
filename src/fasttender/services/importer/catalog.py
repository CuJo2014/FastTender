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
"""

from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import DataSource, DataSourceStatus, DataSourceType, Item
from fasttender.services.importer.types import (
    DuplicateArticle,
    ImportError,
    ImportMode,
    ImportReport,
    RowError,
)
from fasttender.services.parser import (
    ParsedItem,
    ParseError,
    SpecificationParser,
)
from fasttender.services.parser.value_normalizer import (
    normalize_article,
    normalize_name,
)

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

        # Валидация и дедупликация внутри файла
        valid_items, seen_articles = self._validate_and_dedupe(parse_result.items, report)

        if mode is ImportMode.REPLACE:
            report.rows_deactivated = await self._deactivate_existing(session, source.id)
            new_items = self._build_orm_items(source.id, valid_items)
            session.add_all(new_items)
            report.rows_imported = len(new_items)
        elif mode is ImportMode.MERGE:
            imported, updated = await self._upsert(session, source.id, valid_items)
            report.rows_imported = imported
            report.rows_updated = updated
        else:  # защита от расширения enum'а в будущем
            raise ImportError(f"Неизвестный режим импорта: {mode}")

        # Обновляем метку last_synced_at источника
        source.last_synced_at = _now_utc()
        # На случай если используется уже скрытый seen_articles
        _ = seen_articles

        return report

    # --- Внутренние методы ---

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

    @staticmethod
    def _validate_and_dedupe(
        items: list[ParsedItem], report: ImportReport
    ) -> tuple[list[ParsedItem], dict[str, int]]:
        """Отсеивает невалидные строки и дубли артикулов внутри файла.

        Дубликат = две строки с одинаковым `article_normalized` (не NULL).
        Оставляем первую, остальные попадают в report.duplicates.
        """
        seen: dict[str, int] = {}  # article_normalized → line_number
        duplicates: dict[str, list[int]] = {}
        valid: list[ParsedItem] = []

        for item in items:
            if not item.name or not item.name.strip():
                report.errors.append(
                    RowError(
                        line_number=item.line_number,
                        reason="empty_name",
                        raw=item.raw_row,
                    )
                )
                report.rows_skipped += 1
                continue

            article_norm = normalize_article(item.article)
            if article_norm is not None:
                if article_norm in seen:
                    duplicates.setdefault(article_norm, []).append(item.line_number)
                    report.rows_skipped += 1
                    continue
                seen[article_norm] = item.line_number

            valid.append(item)

        report.duplicates = [
            DuplicateArticle(
                article=article,
                first_line=seen[article],
                duplicate_lines=lines,
            )
            for article, lines in duplicates.items()
        ]
        return valid, seen

    @staticmethod
    def _build_orm_items(source_id, items: list[ParsedItem]) -> list[Item]:  # type: ignore[no-untyped-def]
        """Маппинг ParsedItem → Item для bulk-insert.

        attributes остаётся {} — в Фазе 1 характеристики не извлекаются (раздел 4.2).
        """
        orm_items: list[Item] = []
        for item in items:
            orm_items.append(
                Item(
                    source_id=source_id,
                    article_raw=item.article,
                    article_normalized=normalize_article(item.article),
                    name=item.name,
                    name_normalized=normalize_name(item.name),
                    manufacturer=item.manufacturer,
                    manufacturer_normalized=(
                        item.manufacturer.lower() if item.manufacturer else None
                    ),
                    price=item.price,
                    currency=item.currency,
                    unit=item.unit,
                    in_stock=True,
                    attributes={},
                    is_active=True,
                )
            )
        return orm_items

    @classmethod
    async def _deactivate_existing(cls, session: AsyncSession, source_id) -> int:  # type: ignore[no-untyped-def]
        """Replace-режим: помечает все позиции источника is_active=false.

        Физическое удаление не делаем — на эти Item могут ссылаться MatchCandidate
        и Verification в истории обработанных спецификаций. Деактивация
        исключает их из новых поисков (фильтр is_active=true в матчере).
        """
        result = await session.execute(
            update(Item).where(Item.source_id == source_id).values(is_active=False)
        )
        return result.rowcount or 0

    @classmethod
    async def _upsert(
        cls,
        session: AsyncSession,
        source_id,  # type: ignore[no-untyped-def]
        items: list[ParsedItem],
    ) -> tuple[int, int]:
        """Merge-режим: обновляет существующие по article_normalized, остальные INSERT."""
        articles = [a for a in (normalize_article(i.article) for i in items) if a is not None]
        existing: dict[str, Item] = {}
        if articles:
            stmt = select(Item).where(
                Item.source_id == source_id,
                Item.article_normalized.in_(articles),
            )
            for row in (await session.scalars(stmt)).all():
                if row.article_normalized:
                    existing[row.article_normalized] = row

        imported = 0
        updated = 0
        for item in items:
            article_norm = normalize_article(item.article)
            target = existing.get(article_norm) if article_norm else None
            if target is not None:
                target.article_raw = item.article
                target.name = item.name
                target.name_normalized = normalize_name(item.name)
                target.manufacturer = item.manufacturer
                target.manufacturer_normalized = (
                    item.manufacturer.lower() if item.manufacturer else None
                )
                target.price = item.price
                target.currency = item.currency
                target.unit = item.unit
                target.is_active = True
                updated += 1
            else:
                session.add(
                    Item(
                        source_id=source_id,
                        article_raw=item.article,
                        article_normalized=article_norm,
                        name=item.name,
                        name_normalized=normalize_name(item.name),
                        manufacturer=item.manufacturer,
                        manufacturer_normalized=(
                            item.manufacturer.lower() if item.manufacturer else None
                        ),
                        price=item.price,
                        currency=item.currency,
                        unit=item.unit,
                        in_stock=True,
                        attributes={},
                        is_active=True,
                    )
                )
                imported += 1
        return imported, updated


def _now_utc():  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    return datetime.now(UTC)
