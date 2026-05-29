"""Общая логика: matrix (list[list]) → ParseResult.

Используется и Excel-парсером (excel.py), и CSV-парсером (csv.py) — оба сводят
свой формат к плоской матрице значений, а дальше код общий.
"""

from collections.abc import Sequence
from typing import Any

from fasttender.services.parser.header_detector import detect_header
from fasttender.services.parser.types import (
    ColumnMapping,
    ParsedItem,
    ParseError,
    ParseResult,
    ParseWarning,
    SpecField,
)
from fasttender.services.parser.value_normalizer import clean_string, parse_decimal


def build_result(
    matrix: Sequence[Sequence[Any]],
    *,
    sheet_name: str | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
    mapping_override: ColumnMapping | None = None,
) -> ParseResult:
    """Превращает плоскую матрицу в ParseResult: автоопределение шапки + извлечение строк."""
    if not matrix:
        raise ParseError("Файл пуст", details={"sheet": sheet_name})

    if mapping_override is not None and mapping_override.is_usable:
        header_row = 0
        mapping = mapping_override
    else:
        detected = detect_header(matrix)
        if detected is None:
            raise ParseError(
                "Не удалось определить строку шапки. Требуется ручной маппинг колонок.",
                details={
                    "sheet": sheet_name,
                    "rows_scanned": min(len(matrix), 30),
                },
            )
        header_row, mapping = detected

    items, warnings = _extract_items(matrix, header_row + 1, mapping)

    return ParseResult(
        items=items,
        warnings=warnings,
        sheet_name=sheet_name,
        header_row=header_row,
        column_mapping=mapping,
        encoding=encoding,
        delimiter=delimiter,
    )


def _extract_items(
    matrix: Sequence[Sequence[Any]],
    start_row: int,
    mapping: ColumnMapping,
) -> tuple[list[ParsedItem], list[ParseWarning]]:
    items: list[ParsedItem] = []
    warnings: list[ParseWarning] = []
    line_number = 0

    name_col = mapping.get(SpecField.NAME)
    if name_col is None:
        raise ParseError("В маппинге колонок отсутствует обязательное поле NAME")

    for row_idx in range(start_row, len(matrix)):
        row = matrix[row_idx]
        if not row:
            continue

        name = clean_string(_cell(row, name_col))
        if not name:
            continue

        line_number += 1

        article = clean_string(_cell(row, mapping.get(SpecField.ARTICLE)))
        manufacturer = clean_string(_cell(row, mapping.get(SpecField.MANUFACTURER)))
        category = clean_string(_cell(row, mapping.get(SpecField.CATEGORY)))
        unit = clean_string(_cell(row, mapping.get(SpecField.UNIT)))
        currency = clean_string(_cell(row, mapping.get(SpecField.CURRENCY)))
        delivery_term = clean_string(_cell(row, mapping.get(SpecField.DELIVERY_TERM)))
        notes = clean_string(_cell(row, mapping.get(SpecField.NOTES)))

        quantity_raw = _cell(row, mapping.get(SpecField.QUANTITY))
        quantity = parse_decimal(quantity_raw)
        if quantity_raw is not None and quantity is None:
            warnings.append(
                ParseWarning(
                    line_number=line_number,
                    field=SpecField.QUANTITY,
                    message="Не удалось распознать количество как число",
                    raw_value=str(quantity_raw),
                )
            )

        price_raw = _cell(row, mapping.get(SpecField.PRICE))
        price = parse_decimal(price_raw)
        if price_raw is not None and price is None:
            warnings.append(
                ParseWarning(
                    line_number=line_number,
                    field=SpecField.PRICE,
                    message="Не удалось распознать цену как число",
                    raw_value=str(price_raw),
                )
            )

        raw_row = {
            f"col_{idx}": str(value) if value is not None else None for idx, value in enumerate(row)
        }

        items.append(
            ParsedItem(
                line_number=line_number,
                name=name,
                article=article,
                manufacturer=manufacturer,
                category=category,
                quantity=quantity,
                unit=unit,
                price=price,
                currency=currency,
                delivery_term=delivery_term,
                notes=notes,
                raw_row=raw_row,
            )
        )

    return items, warnings


def _cell(row: Sequence[Any], col_idx: int | None) -> Any:
    if col_idx is None:
        return None
    if col_idx < 0 or col_idx >= len(row):
        return None
    return row[col_idx]
