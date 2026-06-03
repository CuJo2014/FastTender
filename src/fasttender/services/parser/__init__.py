"""Парсер входящих спецификаций (раздел 4.1, 10).

Поддерживаемые форматы Фазы 1: XLSX, XLSM, XLS, CSV, TSV.

Использование:

    from fasttender.services.parser import SpecificationParser, ParseError

    parser = SpecificationParser()
    try:
        result = parser.parse(Path("spec.xlsx"))
    except ParseError as exc:
        # Не удалось определить шапку — нужен ручной маппинг колонок
        ...
    else:
        for item in result.items:
            print(item.line_number, item.name, item.article, item.quantity)
"""

from pathlib import Path

from fasttender.services.parser.csv import parse_csv
from fasttender.services.parser.excel import parse_excel
from fasttender.services.parser.types import (
    ColumnMapping,
    ParsedItem,
    ParseError,
    ParseResult,
    ParseWarning,
    PriceEntry,
    SpecField,
    VatBasis,
)

__all__ = [
    "ColumnMapping",
    "ParseError",
    "ParseResult",
    "ParseWarning",
    "ParsedItem",
    "PriceEntry",
    "SpecField",
    "SpecificationParser",
    "VatBasis",
]

_EXCEL_EXT = {".xlsx", ".xlsm", ".xls"}
_CSV_EXT = {".csv", ".tsv", ".txt"}


class SpecificationParser:
    """Фасад над форматами Фазы 1.

    В Фазе 2 здесь же появятся DOCX, PDF, OCR-ветки (см. раздел 10.1).
    """

    def parse(
        self,
        path: Path | str,
        *,
        sheet_name: str | None = None,
        mapping_override: ColumnMapping | None = None,
        header_row_override: int | None = None,
        encoding_override: str | None = None,
        delimiter_override: str | None = None,
        exclude_fields: frozenset[SpecField] | None = None,
    ) -> ParseResult:
        """Парсит файл и возвращает ParseResult.

        Args:
            path: путь к файлу.
            sheet_name: имя листа (только для Excel).
            mapping_override: ручной маппинг колонок (fallback по разделу 4.1.4).
                              Если задан с полем NAME, автоопределение шапки пропускается.
            encoding_override: явная кодировка для CSV (например, "cp1251").
            delimiter_override: явный разделитель для CSV (например, ";").

        Raises:
            ParseError: формат не поддержан, файл повреждён, шапка не определена.
        """
        path = Path(path)
        if not path.exists():
            raise ParseError(f"Файл не найден: {path}")
        if not path.is_file():
            raise ParseError(f"Это не файл: {path}")

        ext = path.suffix.lower()
        if ext in _EXCEL_EXT:
            return parse_excel(
                path,
                sheet_name=sheet_name,
                mapping_override=mapping_override,
                header_row_override=header_row_override,
                exclude_fields=exclude_fields,
            )
        if ext in _CSV_EXT:
            return parse_csv(
                path,
                mapping_override=mapping_override,
                header_row_override=header_row_override,
                encoding_override=encoding_override,
                delimiter_override=delimiter_override,
                exclude_fields=exclude_fields,
            )

        raise ParseError(
            f"Неподдерживаемое расширение: {ext}. Фаза 1: {sorted(_EXCEL_EXT | _CSV_EXT)}",
            details={"path": str(path)},
        )

    @staticmethod
    def supported_extensions() -> set[str]:
        return _EXCEL_EXT | _CSV_EXT
