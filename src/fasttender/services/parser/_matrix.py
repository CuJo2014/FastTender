"""Общая логика: matrix (list[list]) → ParseResult.

Используется и Excel-парсером (excel.py), и CSV-парсером (csv.py) — оба сводят
свой формат к плоской матрице значений, а дальше код общий.
"""

from collections.abc import Sequence
from typing import Any

from fasttender.services.parser.header_detector import detect_header
from fasttender.services.parser.price_columns import (
    PriceColumn,
    detect_price_columns,
    select_preferred,
)
from fasttender.services.parser.types import (
    ColumnMapping,
    ParsedItem,
    ParseError,
    ParseResult,
    ParseWarning,
    PriceEntry,
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
    header_row_override: int | None = None,
    exclude_fields: frozenset[SpecField] | None = None,
) -> ParseResult:
    """Превращает плоскую матрицу в ParseResult: автоопределение шапки + извлечение строк.

    header_row_override: индекс строки шапки при использовании mapping_override.
    Нужен для прайсов где шапка НЕ на первой строке (TEL — row4, MIL — row9):
    при ре-импорте сохранённый маппинг применяется к правильной строке, а не к 0.
    Без override (автодетект) — игнорируется.
    """
    if not matrix:
        raise ParseError("Файл пуст", details={"sheet": sheet_name})

    if mapping_override is not None and mapping_override.is_usable:
        header_row = header_row_override if header_row_override is not None else 0
        mapping = mapping_override
        # Если override содержит поле из exclude_fields — убираем (например,
        # старый кэш source.config с code_1c для прайса поставщика)
        if exclude_fields:
            mapping = ColumnMapping(
                columns={f: c for f, c in mapping.columns.items() if f not in exclude_fields}
            )
    else:
        detected = detect_header(matrix, exclude_fields=exclude_fields)
        if detected is None:
            raise ParseError(
                "Не удалось определить строку шапки. Требуется ручной маппинг колонок.",
                details={
                    "sheet": sheet_name,
                    "rows_scanned": min(len(matrix), 30),
                },
            )
        header_row, mapping = detected

    # Все ценовые колонки шапки (несколько цен на позицию). Не зависит от
    # field-mapping — детектится по заголовкам реальной строки шапки.
    price_columns = detect_price_columns(matrix, header_row)

    items, warnings = _extract_items(matrix, header_row + 1, mapping, price_columns)

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
    price_columns: Sequence[PriceColumn] | None = None,
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
        code_1c = clean_string(_cell(row, mapping.get(SpecField.CODE_1C)))
        manufacturer = clean_string(_cell(row, mapping.get(SpecField.MANUFACTURER)))
        category = clean_string(_cell(row, mapping.get(SpecField.CATEGORY)))
        attributes = clean_string(_cell(row, mapping.get(SpecField.ATTRIBUTES)))
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

        # Несколько цен на позицию: вытягиваем все распознанные ценовые
        # колонки. Основная (price) — preferred из них (net>gross>unknown).
        prices = _extract_prices(row, price_columns)
        if prices:
            preferred = select_preferred(prices)
            price = preferred.amount if preferred is not None else None
        else:
            # Fallback: ценовых колонок не распознано (например, override-
            # маппинг с нечитаемыми заголовками) — берём mapped PRICE напрямую.
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
                code_1c=code_1c,
                manufacturer=manufacturer,
                category=category,
                attributes=attributes,
                quantity=quantity,
                unit=unit,
                price=price,
                currency=currency,
                delivery_term=delivery_term,
                notes=notes,
                prices=prices,
                raw_row=raw_row,
            )
        )

    return items, warnings


def _extract_prices(
    row: Sequence[Any], price_columns: Sequence[PriceColumn] | None
) -> list[PriceEntry]:
    """Строит список цен строки по схеме ценовых колонок. Пустые/нечисловые
    ячейки пропускаются — позиция может иметь не все цены заполненными."""
    if not price_columns:
        return []
    out: list[PriceEntry] = []
    for pc in price_columns:
        amount = parse_decimal(_cell(row, pc.col_index))
        if amount is None:
            continue
        out.append(PriceEntry(amount=amount, vat=pc.vat, tier=pc.tier, label=pc.label))
    return out


def _cell(row: Sequence[Any], col_idx: int | None) -> Any:
    if col_idx is None:
        return None
    if col_idx < 0 or col_idx >= len(row):
        return None
    return row[col_idx]
