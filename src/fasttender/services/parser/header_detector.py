"""Автоопределение строки шапки и маппинга колонок (раздел 10.2).

Алгоритм:
  1. Просматриваем первые N строк (по умолчанию 30).
  2. Для каждой строки считаем «header score» — сколько ячеек узнаются как
     заголовок одного из логических полей по словарю синонимов.
  3. Строка с максимальным score (если ≥ порога) — шапка.
  4. Строим ColumnMapping из найденных совпадений.

Если score ниже порога — возвращаем None, и фасад должен попросить ручной маппинг
(fallback по разделу 4.1.4).

Синонимы — стартовый набор для русскоязычных файлов (B1: только русский).
Расширяется через накопление обратной связи (раздел 9.5).
"""

import re
from collections.abc import Sequence
from typing import Any

from fasttender.services.parser.types import ColumnMapping, SpecField
from fasttender.services.parser.value_normalizer import clean_string

# Словарь синонимов: для каждого логического поля — список нормализованных
# (lowercase) заголовков. При сопоставлении заголовок ячейки тоже приводится
# к lowercase и проверяется на «начинается с» или «совпадает».
COLUMN_SYNONYMS: dict[SpecField, tuple[str, ...]] = {
    SpecField.NAME: (
        "наименование",
        "название",
        "товар",
        "продукция",
        "описание",
        "номенклатура",
        "позиция",
        "name",
        "item",
        "description",
        "product",
    ),
    SpecField.ARTICLE: (
        "артикул",
        "код",
        "арт",
        "арт.",
        "sku",
        "номер",
        "код товара",
        "артикул товара",
        "артикул производителя",
        "article",
        "code",
        "part number",
        "p/n",
    ),
    SpecField.MANUFACTURER: (
        "производитель",
        "бренд",
        "марка",
        "изготовитель",
        "вендор",
        "поставщик",
        "manufacturer",
        "brand",
        "vendor",
    ),
    SpecField.QUANTITY: (
        "количество",
        "кол-во",
        "колво",
        "кол",
        "к-во",
        "qty",
        "quantity",
        "amount",
    ),
    SpecField.UNIT: (
        "ед",
        "ед.",
        "ед изм",
        "ед. изм",
        "ед.изм",
        "ед. изм.",
        "единица",
        "единица измерения",
        "unit",
        "uom",
    ),
    SpecField.PRICE: (
        "цена",
        "стоимость",
        "цена за единицу",
        "цена за ед",
        "price",
        "unit price",
        "cost",
    ),
    SpecField.CURRENCY: (
        "валюта",
        "currency",
    ),
    SpecField.DELIVERY_TERM: (
        "срок",
        "срок поставки",
        "доставка",
        "delivery",
        "lead time",
    ),
    SpecField.NOTES: (
        "примечание",
        "примечания",
        "комментарий",
        "комментарии",
        "note",
        "notes",
        "comment",
    ),
}

# Порядок проверки важен: более специфичные поля раньше, чтобы
# «цена за единицу» не схватилась как UNIT по слову «единицу».
_FIELD_PRIORITY: tuple[SpecField, ...] = (
    SpecField.ARTICLE,
    SpecField.NAME,
    SpecField.MANUFACTURER,
    SpecField.QUANTITY,
    SpecField.PRICE,
    SpecField.CURRENCY,
    SpecField.UNIT,
    SpecField.DELIVERY_TERM,
    SpecField.NOTES,
)


def _normalize_header_cell(value: Any) -> str | None:
    """Готовит заголовок для сравнения: lowercase, без лишней пунктуации."""
    s = clean_string(value)
    if s is None:
        return None
    s = s.lower()
    # Убираем переводы строк внутри заголовка
    s = re.sub(r"\s+", " ", s)
    return s


def _match_field(header_text: str) -> SpecField | None:
    """Сопоставляет одну ячейку шапки с логическим полем.

    Стратегия: ячейка совпадает с синонимом точно ИЛИ начинается с него
    (с учётом границы слова). Это ловит варианты вроде "Артикул товара".
    """
    for field in _FIELD_PRIORITY:
        for synonym in COLUMN_SYNONYMS[field]:
            if header_text == synonym:
                return field
            # «Начинается с» с границей слова (пробел или конец строки)
            if header_text.startswith(synonym):
                tail = header_text[len(synonym) :]
                if not tail or tail[0] in " :-.,/":
                    return field
            # Содержит как отдельное слово (через пробел, без границ)
            if f" {synonym} " in f" {header_text} ":
                return field
    return None


def _score_row(row: Sequence[Any]) -> tuple[int, ColumnMapping]:
    """Считает header score для строки и одновременно строит маппинг."""
    mapping = ColumnMapping()
    score = 0
    for col_idx, cell in enumerate(row):
        text = _normalize_header_cell(cell)
        if not text:
            continue
        field = _match_field(text)
        if field is None:
            continue
        # Если поле уже занято — не перезаписываем (первое совпадение «побеждает»)
        if not mapping.has(field):
            mapping.columns[field] = col_idx
            score += 1
    return score, mapping


def detect_header(
    rows: Sequence[Sequence[Any]],
    *,
    max_scan_rows: int = 30,
    min_score: int = 2,
) -> tuple[int, ColumnMapping] | None:
    """Определяет строку шапки и строит ColumnMapping.

    Args:
        rows: первые строки таблицы (вся таблица или её начало).
        max_scan_rows: сколько строк просматривать сверху.
        min_score: минимальное число распознанных колонок, чтобы считать строку шапкой.
                   Меньше — слишком высок риск принять за шапку случайный текст.

    Returns:
        (header_row_index, mapping) если шапка найдена и в ней есть колонка
        наименования; иначе None.
    """
    best_row: int | None = None
    best_score = 0
    best_mapping: ColumnMapping | None = None

    for idx, row in enumerate(rows[:max_scan_rows]):
        score, mapping = _score_row(row)
        if score > best_score and mapping.has(SpecField.NAME):
            best_score = score
            best_row = idx
            best_mapping = mapping

    if best_row is None or best_mapping is None or best_score < min_score:
        return None

    return best_row, best_mapping
