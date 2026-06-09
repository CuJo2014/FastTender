"""Преобразование значений ячеек в типизированные поля.

Реальные Excel-таблицы содержат числа как текст («≈10», «10-12», «10 шт»),
десятичную запятую вперемешку с точкой, неразрывные пробелы и прочие сюрпризы
(раздел 4.1.4). Эти функции — чистые, легко тестируются.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

# Неразрывный пробел и прочая «невидимая» нечисть, которая ломает int()/Decimal()
_INVISIBLE_CHARS = (" ", " ", " ", "​", "﻿")

# Распознавание числа в свободном тексте: опциональный знак ≈/~/±, число, опциональный хвост («шт», «м», …)
# Захватываем первое же число в строке. Для интервалов «10-12» берём левую границу.
_NUMBER_RE = re.compile(
    r"""
    (?:[≈~±]\s*)?              # необязательный модификатор «приблизительно»
    ([+-]?\d{1,3}(?:[  ]?\d{3})*  # целая часть с разделителями тысяч (пробел или nbsp)
       (?:[.,]\d+)?            # необязательная дробная часть с . или ,
       |
       [+-]?[.,]\d+)           # либо число без целой части типа ",5"
    """,
    re.VERBOSE,
)


def clean_string(value: Any) -> str | None:
    """Приводит произвольное значение к строке без мусорных символов.

    Возвращает None для пустых/None значений.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value
    else:
        s = str(value)
    for ch in _INVISIBLE_CHARS:
        s = s.replace(ch, " ")
    s = " ".join(s.split())  # схлопывает все пробелы
    return s or None


def normalize_article(value: Any) -> str | None:
    """Артикул для поиска: uppercase, без пробелов/дефисов/точек/слешей.

    Оригинал сохраняется отдельно (article_raw). Это нужно для exact-матча
    после нормализации (раздел 9.1 уровень 1).
    """
    s = clean_string(value)
    if s is None:
        return None
    # Убираем популярные разделители внутри артикула: пробелы, дефис, точка, слеш, звёздочка
    cleaned = re.sub(r"[\s\-./*\\]+", "", s)
    return cleaned.upper() or None


def normalize_name(value: Any) -> str | None:
    """Наименование для поиска: lowercase, нормализованные пробелы.

    Сохраняет оригинал в name_raw (это делает вызывающий код).
    """
    s = clean_string(value)
    if s is None:
        return None
    return s.lower()


# Хвост-единица измерения/размерность — такие токены НЕ артикулы
# («200мм», «4мм», «32вт»). Проверяем окончание токена.
_DIM_SUFFIX_RE = re.compile(
    r"(мм|см|дм|км|м|кг|гр|г|мг|т|л|мл|шт|компл|уп|вт|квт|в|ма|а|гц)$",
    re.IGNORECASE,
)


def extract_article_candidates(name: Any) -> list[str]:
    """Вытаскивает из наименования токены, похожие на артикул/модель.

    Клиентские спеки часто без отдельной колонки артикула, но код/модель
    зашиты в текст имени: «Шнур ... Tarkett 91928», «Пылесос Einhell TE-VC
    2340 SA 2342380». Такие токены можно сопоставить с `article` каталога
    (уровни 1/2), чтобы поднять confidence (раздел 9.1).

    Токен считается кандидатом, если содержит цифру и при этом:
      - буквенно-цифровой (модель: «TE-VC», «КЭВ-32M3», «M12») длиной ≥ 3, ИЛИ
      - чисто-цифровой длиной ≥ 5 (SKU; короткие числа — это размеры/кол-во).
    Размерности с единицей («200мм», «4мм») отбрасываются.

    Возвращает нормализованные (как `normalize_article`) уникальные коды,
    в порядке появления.
    """
    s = clean_string(name)
    if s is None:
        return []
    candidates: list[str] = []
    seen: set[str] = set()
    for raw_token in re.split(r"[\s,;()\[\]]+", s):
        token = raw_token.strip(" .,:;")
        if not token or not any(ch.isdigit() for ch in token):
            continue
        if _DIM_SUFFIX_RE.search(token):
            continue  # размерность/единица, не артикул
        has_alpha = any(ch.isalpha() for ch in token)
        digit_count = sum(ch.isdigit() for ch in token)
        if not has_alpha and digit_count < 5:
            continue  # короткое число — размер/количество, не SKU
        normalized = normalize_article(token)
        if normalized and len(normalized) >= 3 and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    return candidates


def extract_code_tokens(text: Any) -> list[str]:
    """Длинные цифровые серии (≥5 цифр) из текста — для поиска кода в
    НАИМЕНОВАНИИ каталога, когда модель/код зашиты в имя, а не в артикул.

    Пример: «5т Д1-3913010-50 ШААЗ» → ['3913010']; матчится по подстроке с
    каталожным «Домкрат гидравлический ДГ15-3913010-03» и «Домкрат 4523913010».
    Короткие числа (размеры/количество/тоннаж) отсекаются порогом длины ≥5 —
    они слишком частотны и дали бы ложные совпадения.

    Возвращает уникальные серии в порядке появления (в нижнем регистре —
    name_normalized тоже lowercase).
    """
    s = clean_string(text)
    if s is None:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for run in re.findall(r"\d{5,}", s):
        if run not in seen:
            seen.add(run)
            out.append(run)
    return out


def parse_decimal(value: Any) -> Decimal | None:
    """Извлекает Decimal из произвольного значения.

    Поддерживает:
      - числа: int, float, Decimal
      - строки с десятичной запятой: "1,5" → 1.5
      - строки с разделителем тысяч: "1 234,5" → 1234.5
      - «грязные» строки: "≈10", "10 шт", "10-12" (берёт первое число)

    Возвращает None, если число не удалось распознать.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # bool — подтип int в Python, но в спецификации это явно мусор
        return None
    if isinstance(value, int | float | Decimal):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    s = clean_string(value)
    if s is None:
        return None

    match = _NUMBER_RE.search(s)
    if not match:
        return None

    raw = match.group(1)
    # Убираем разделители тысяч (пробелы), запятую заменяем на точку
    cleaned = raw.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_int(value: Any) -> int | None:
    d = parse_decimal(value)
    if d is None:
        return None
    try:
        return int(d)
    except (ValueError, OverflowError):
        return None
