"""Импорт прайса поставщика (раздел 4.3, 16.3 пункт 3).

Phase 1:
  - Один DataSource типа SUPPLIER_PRICELIST на поставщика (создаётся лениво).
  - Шаблон маппинга колонок (раздел 4.3.1) хранится в source.config["column_mapping"]:
    при наличии — применяется как override; иначе срабатывает автодетект,
    после успешного импорта определённый маппинг сохраняется в config.
    Эффект: система «учится» по первой удачной загрузке от поставщика.
  - История версий (раздел 4.3.3) — Фаза 2.
  - Регулярные загрузки по расписанию (раздел 4.3.4) — Фаза 2.
"""

from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fasttender.models import DataSource, DataSourceStatus, DataSourceType, Supplier
from fasttender.services.importer._base import apply_to_source, validate_and_dedupe
from fasttender.services.importer.transformations import (
    SupplierTransformations,
    apply_transformations,
)
from fasttender.services.importer.types import (
    ImportError,
    ImportMode,
    ImportReport,
)
from fasttender.services.parser import (
    ColumnMapping,
    ParseError,
    SpecField,
    SpecificationParser,
)

CONFIG_KEY_MAPPING = "column_mapping"
CONFIG_KEY_HEADER_ROW = "header_row"


class PriceListImporter:
    """Импортирует прайс одного поставщика из файла Excel/CSV.

    Использование:

        importer = PriceListImporter()
        async with session_factory() as session:
            report = await importer.import_file(
                session,
                supplier_id=UUID("..."),
                path=Path("supplier_xyz_2026-05.xlsx"),
                mode=ImportMode.REPLACE,
            )
            await session.commit()
    """

    def __init__(self, parser: SpecificationParser | None = None) -> None:
        self._parser = parser or SpecificationParser()

    async def import_file(
        self,
        session: AsyncSession,
        *,
        supplier_id: UUID,
        path: Path,
        mode: ImportMode = ImportMode.REPLACE,
        sheet_name: str | None = None,
        mapping_override: ColumnMapping | None = None,
        header_row_override: int | None = None,
    ) -> ImportReport:
        supplier = await session.get(Supplier, supplier_id)
        if supplier is None:
            raise ImportError(
                f"Поставщик {supplier_id} не найден",
                details={"supplier_id": str(supplier_id)},
            )

        source = await self._get_or_create_pricelist_source(session, supplier)
        # Маппинг и строку шапки берём из явного override либо из выученного
        # config. header_row критичен для прайсов где шапка не на первой строке
        # (TEL — row4, MIL — row9): иначе ре-импорт по сохранённому маппингу
        # читает не ту строку и теряет цены (и данные).
        effective_mapping: ColumnMapping | None
        if mapping_override is not None:
            effective_mapping = mapping_override
            effective_header_row = header_row_override
        else:
            effective_mapping = self._mapping_from_config(source.config)
            effective_header_row = (
                self._header_row_from_config(source.config)
                if effective_mapping is not None
                else None
            )

        try:
            # У поставщиков НЕ бывает Кода 1С — это внутренний идентификатор
            # каталога компании. Запрещаем парсеру детектить колонку, иначе
            # «Код ТНВЭД» / «Код товара поставщика» / «HS code» ошибочно
            # попадают в code_1c и схлопывают всё через dedupe.
            parse_result = self._parser.parse(
                path,
                sheet_name=sheet_name,
                mapping_override=effective_mapping,
                header_row_override=effective_header_row,
                exclude_fields=frozenset({SpecField.CODE_1C}),
            )
        except ParseError as exc:
            raise ImportError(
                f"Не удалось распарсить прайс: {exc}",
                details=exc.details,
            ) from exc

        # Если шаблона не было — учим: сохраняем автодетектированный маппинг
        # вместе со строкой шапки (нужна для ре-импорта, см. выше).
        if effective_mapping is None:
            self._save_mapping_to_config(
                source, parse_result.column_mapping, parse_result.header_row
            )

        # Применяем конфигурируемые трансформации поставщика (бренд из
        # имени, НДС, дефолты) — до dedupe/upsert
        transformations = SupplierTransformations.from_meta(supplier.meta)
        transformed_items = apply_transformations(parse_result.items, transformations)

        report = ImportReport(
            source_id=str(source.id),
            source_name=source.name,
            mode=mode,
            rows_total=len(transformed_items),
        )

        valid_items = validate_and_dedupe(transformed_items, report)
        await apply_to_source(
            session,
            source,
            valid_items,
            mode,
            report,
            supplier_prefix=supplier.prefix,
        )
        return report

    # --- Внутренние методы ---

    @staticmethod
    async def _get_or_create_pricelist_source(
        session: AsyncSession, supplier: Supplier
    ) -> DataSource:
        """В Phase 1 — один прайс-источник на поставщика.

        В Phase 2 при появлении нескольких прайсов от одного поставщика
        (например, основной + спецпредложения) добавится дополнительное
        измерение (имя прайса в config или отдельная сущность).
        """
        stmt = select(DataSource).where(
            DataSource.type == DataSourceType.SUPPLIER_PRICELIST,
            DataSource.supplier_id == supplier.id,
        )
        existing = await session.scalar(stmt)
        if existing is not None:
            return existing

        source = DataSource(
            type=DataSourceType.SUPPLIER_PRICELIST,
            name=f"Прайс: {supplier.name}",
            supplier_id=supplier.id,
            status=DataSourceStatus.ACTIVE,
            config={},
        )
        session.add(source)
        await session.flush()
        return source

    @staticmethod
    def _mapping_from_config(config: dict) -> ColumnMapping | None:
        """Достаёт сохранённый шаблон маппинга из source.config.

        Формат в config:
            {"column_mapping": {"name": 0, "article": 1, "quantity": 2, ...}}
        """
        raw = config.get(CONFIG_KEY_MAPPING)
        if not raw or not isinstance(raw, dict):
            return None
        columns: dict[SpecField, int] = {}
        for field_name, col_idx in raw.items():
            try:
                field = SpecField(field_name)
                columns[field] = int(col_idx)
            except (ValueError, TypeError):
                # Игнорируем кривые поля — это не критичная ошибка, просто
                # отвалится на отсутствии NAME, и парсер сделает автодетект
                continue
        mapping = ColumnMapping(columns=columns)
        return mapping if mapping.is_usable else None

    @staticmethod
    def _header_row_from_config(config: dict) -> int | None:
        """Достаёт сохранённую строку шапки (0-based) из source.config."""
        raw = config.get(CONFIG_KEY_HEADER_ROW)
        if isinstance(raw, int) and raw >= 0:
            return raw
        return None

    @staticmethod
    def _save_mapping_to_config(
        source: DataSource, mapping: ColumnMapping, header_row: int | None
    ) -> None:
        """Сохраняет автодетектированный маппинг + строку шапки для следующих
        загрузок.

        SQLAlchemy не отслеживает мутации dict внутри JSONB по умолчанию,
        поэтому пересоздаём весь config.
        """
        new_config = dict(source.config) if source.config else {}
        new_config[CONFIG_KEY_MAPPING] = {
            field.value: col_idx for field, col_idx in mapping.columns.items()
        }
        if header_row is not None:
            new_config[CONFIG_KEY_HEADER_ROW] = header_row
        source.config = new_config
