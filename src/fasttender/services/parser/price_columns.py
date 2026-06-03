"""Детектор ВСЕХ ценовых колонок в шапке прайса (задача «Парсинг цен»).

В отличие от `header_detector`, который выбирает ОДНУ колонку на каждое
логическое поле (включая одну PRICE), здесь мы извлекаем *все* ценовые
колонки строки шапки с разметкой:

- база НДС (`vat`): net (без НДС) / gross (с НДС) / unknown;
- уровень (`tier`): группирующий заголовок из строки над шапкой, если есть.
  Пример TEL: над парами «c НДС / без НДС» стоят «Цены с вашей скидкой»
  (закупка), «РРЦ», «МИЦ».

Зачем: в реальных прайсах на позицию приходится несколько цен
(см. `fasttender-price-storage-decisions`): пары «с НДС»/«без НДС»,
розница/опт/акция, «с ТЗР». Старый детектор брал первую совпавшую и
терял остальные, а для TEL не находил вовсе (заголовок — просто «c НДС»).

Функция НЕ решает, какую цену считать основной — это per-supplier выбор
на уровне выше. Здесь только честная инвентаризация колонок.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fasttender.services.parser.value_normalizer import clean_string


class VatBasis(StrEnum):
    NET = "net"  # без НДС
    GROSS = "gross"  # с НДС
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PriceColumn:
    """Одна ценовая колонка прайса."""

    col_index: int
    label: str  # очищенный (однострочный) заголовок как в файле
    vat: VatBasis
    tier: str | None = None  # группирующий заголовок над колонкой, если есть


# Слова-признаки ценовой колонки. «ндс» сюда НЕ входит намеренно —
# bare «с НДС»/«без НДС» ловится отдельно (_VAT_BARE), чтобы не цеплять
# «Ставка НДС, %».
_PRICE_WORDS: tuple[str, ...] = (
    "цена",
    "стоимост",
    "прайс",
    "ррц",  # рекомендованная розничная цена
    "миц",  # минимальная интернет-цена
    "отпускн",
    "розничн",
    "price",
    "cost",
    "ssp",  # standard selling price (Milwaukee)
)

# Заголовки которые выглядят «ценовыми», но юнит-ценой НЕ являются.
_NOT_PRICE_WORDS: tuple[str, ...] = (
    "сумма",  # AKR «Сумма (руб.)» — итог по строке, не цена за единицу
    "итог",
    "ставка",  # «Ставка НДС»
    "%",
)

# bare «с НДС» / «без НДС» как самостоятельный заголовок (TEL, MIL EN).
# c — латинская тоже (в TEL заголовок «c НДС» через латинскую c).
_VAT_BARE = re.compile(r"\b[сc]\s*ндс\b|\bбез\s*ндс\b")
_VAT_EN = re.compile(r"\bw/?o?\s*vat\b|\bvat\b")


def _norm(value: Any) -> str | None:
    """lowercase + схлопнутые пробелы/переводы строк."""
    s = clean_string(value)
    if s is None:
        return None
    return re.sub(r"\s+", " ", s).lower()


def _one_line(value: Any) -> str | None:
    """Очищенный заголовок без переводов строк — для отображения (label)."""
    s = clean_string(value)
    if s is None:
        return None
    return re.sub(r"\s+", " ", s)


def _vat_basis(norm: str) -> VatBasis:
    # net проверяем ПЕРВЫМ: «без НДС» содержит «ндс», а «w/o vat» содержит «w/».
    if re.search(r"без\s*ндс", norm) or re.search(r"w/o\s*vat|\bw/o\b", norm):
        return VatBasis.NET
    if re.search(r"\b[сc]\s*ндс", norm) or re.search(r"w/\s*vat", norm):
        return VatBasis.GROSS
    return VatBasis.UNKNOWN


def _is_price_column(norm: str) -> bool:
    if any(neg in norm for neg in _NOT_PRICE_WORDS):
        return False
    if any(word in norm for word in _PRICE_WORDS):
        return True
    return bool(_VAT_BARE.search(norm) or _VAT_EN.search(norm))


def _tier_labels(group_row: Sequence[Any]) -> dict[int, str]:
    """Forward-fill группирующей строки: значение «протягивается» вправо до
    следующего непустого (merged-ячейки в openpyxl читаются как одно значение
    в левой-верхней ячейке, остальные — None)."""
    out: dict[int, str] = {}
    current: str | None = None
    for idx, cell in enumerate(group_row):
        label = _one_line(cell)
        if label:
            current = label
        if current:
            out[idx] = current
    return out


def detect_price_columns(
    rows: Sequence[Sequence[Any]],
    header_row_index: int,
    *,
    group_row_index: int | None = None,
) -> list[PriceColumn]:
    """Извлекает все ценовые колонки из строки шапки.

    Args:
        rows: строки таблицы (или её начало).
        header_row_index: индекс строки шапки (0-based) — обычно из `detect_header`.
        group_row_index: индекс строки с группирующими заголовками над шапкой.
            Если None — берётся строка непосредственно над шапкой (если есть).

    Returns:
        Список PriceColumn в порядке колонок. Пустой, если ценовых нет.
    """
    if header_row_index < 0 or header_row_index >= len(rows):
        return []
    header = rows[header_row_index]

    if group_row_index is None:
        group_row_index = header_row_index - 1
    tiers: dict[int, str] = {}
    if 0 <= group_row_index < len(rows) and group_row_index != header_row_index:
        tiers = _tier_labels(rows[group_row_index])

    result: list[PriceColumn] = []
    for col_idx, cell in enumerate(header):
        norm = _norm(cell)
        if not norm or not _is_price_column(norm):
            continue
        result.append(
            PriceColumn(
                col_index=col_idx,
                label=_one_line(cell) or "",
                vat=_vat_basis(norm),
                tier=tiers.get(col_idx),
            )
        )

    # Уровень осмыслен только если он РАЗЛИЧАЕТ ценовые колонки (как у TEL:
    # «Цены с вашей скидкой»/«РРЦ»/«МИЦ»). Если над шапкой не группа, а
    # примечание/счётчик — forward-fill даёт всем колонкам один и тот же
    # ярлык; такой «уровень» — шум, отбрасываем.
    distinct = {c.tier for c in result if c.tier}
    if len(distinct) < 2:
        result = [PriceColumn(c.col_index, c.label, c.vat, None) for c in result]
    return result
