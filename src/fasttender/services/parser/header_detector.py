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
        # NB: «код»/«код 1с» — это CODE_1C (внутренний идентификатор каталога).
        # «код товара» исторически был CODE_1C для 1С-экспортов, но в прайсах
        # поставщиков чаще обозначает их артикул → здесь приоритет ARTICLE
        # (поле проверяется раньше в _FIELD_PRIORITY). Для catalog-импорта
        # 1С-выгрузка обычно имеет «Артикул» + «Код» (без слова «товара»),
        # так что коллизия маловероятна.
        "артикул",
        "арт",
        "арт.",
        "sku",
        "номер",
        "артикул товара",
        "артикул производителя",
        "код товара",  # частый заголовок в прайсах поставщиков
        # «модель» — типично у инструментов и техники, та же роль что артикул
        "модель",
        "модель производителя",
        "model",
        "article",
        "part number",
        "p/n",
    ),
    SpecField.CODE_1C: (
        # NB: бэйр «код» сначала проверяется через _CODE_1C_NEGATIVE на
        # типичные false-positive (ТНВЭД, штрих-код, ОКПД и т.п.)
        "код",
        "код 1с",
        "код1с",
        "код товара",
        "код номенклатуры",
        "код в 1с",
        "code 1c",
        "1c code",
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
    SpecField.CATEGORY: (
        "категория",
        "категория товара",
        "категория товаров",
        "группа",
        "группа товаров",
        "группа товара",
        "раздел",
        "иерархия",
        "подкатегория",
        "родитель",
        "category",
        "group",
        "section",
        "path",
    ),
    SpecField.ATTRIBUTES: (
        "характеристика",
        "характеристики",
        "характеристика товара",
        "характеристики товара",
        "техническая характеристика",
        "технические характеристики",
        "тех характеристики",
        "тех. характеристики",
        "тех.характеристики",
        "характеристики/параметры",
        "параметр",
        "параметры",
        "параметры подбора",
        "технические параметры",
        "тех параметры",
        "тех. параметры",
        "свойство",
        "свойства",
        "characteristic",
        "characteristics",
        "attribute",
        "attributes",
        "parameter",
        "parameters",
        "spec",
        "specs",
        "features",
        "properties",
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
    SpecField.CODE_1C,
    SpecField.NAME,
    SpecField.MANUFACTURER,
    SpecField.CATEGORY,
    SpecField.ATTRIBUTES,
    SpecField.QUANTITY,
    SpecField.PRICE,
    SpecField.CURRENCY,
    SpecField.UNIT,
    SpecField.DELIVERY_TERM,
    SpecField.NOTES,
)

# Заголовки которые НЕ должны попадать в CODE_1C, несмотря на слово «код».
# ТНВЭД — таможенный код, у разных товаров может совпадать.
# Штрих-код — упаковочный, тоже не уникален в нашем смысле.
# ОКПД/ОКВЭД — классификаторы видов экономической деятельности.
_FIELD_NEGATIVES: dict[SpecField, frozenset[str]] = {
    SpecField.CODE_1C: frozenset(
        {
            "код тнвэд",
            "тнвэд",
            "код тн вэд",
            "тн вэд",
            "штрих код",
            "штрих-код",
            "штрихкод",
            "barcode",
            "код страны",
            "country code",
            "код окпд",
            "окпд",
            "код оквэд",
            "оквэд",
            "код упаковки",
        }
    ),
}


def _normalize_header_cell(value: Any) -> str | None:
    """Готовит заголовок для сравнения: lowercase, без лишней пунктуации."""
    s = clean_string(value)
    if s is None:
        return None
    s = s.lower()
    # Убираем переводы строк внутри заголовка
    s = re.sub(r"\s+", " ", s)
    return s


def _synonym_matches(header_text: str, synonym: str) -> bool:
    """Заголовок совпадает с синонимом: точно, «начинается с» (с границей
    слова) или содержит как отдельное слово."""
    if header_text == synonym:
        return True
    # «Начинается с» с границей слова (пробел/пунктуация/конец строки)
    if header_text.startswith(synonym):
        tail = header_text[len(synonym) :]
        if not tail or tail[0] in " :-.,/":
            return True
    # Содержит как отдельное слово — \b ловит границы вокруг пунктуации тоже
    # («Код товара (SKU)» → совпадение по «sku»). re.escape — для p/n и т.п.
    return bool(re.search(rf"\b{re.escape(synonym)}\b", header_text))


def _match_field(
    header_text: str, *, exclude_fields: frozenset[SpecField] | None = None
) -> SpecField | None:
    """Сопоставляет одну ячейку шапки с логическим полем.

    Стратегия: ячейка совпадает с синонимом точно ИЛИ начинается с него
    (с учётом границы слова). Это ловит варианты вроде "Артикул товара".

    exclude_fields: поля, поиск которых нужно вообще пропустить. Например,
    для прайсов поставщиков CODE_1C никогда не применим — это внутренний
    идентификатор каталога компании.

    Negative-list: некоторые поля имеют список запрещённых заголовков
    (ТНВЭД, штрих-код и т.п.) — они проверяются ДО синонимов.
    """
    for field in _FIELD_PRIORITY:
        if exclude_fields and field in exclude_fields:
            continue
        negatives = _FIELD_NEGATIVES.get(field)
        if negatives and header_text in negatives:
            continue  # это false-positive для этого поля, пропускаем
        for synonym in COLUMN_SYNONYMS[field]:
            if _synonym_matches(header_text, synonym):
                return field

    # Прайсы поставщиков: CODE_1C исключён, но колонка «Код» у поставщика —
    # это ИХ артикул/код позиции (пример RUI: «Код» = «ri.377.20»). Без этого
    # у позиции нет стабильного идентификатора → REPLACE-upsert не может
    # сматчить её при ре-импорте (всё деактивируется и вставляется заново).
    # Отдаём код-подобный заголовок в ARTICLE, если ARTICLE не запрещён и это
    # не штрих-код/ТНВЭД (negative-list CODE_1C).
    if (
        exclude_fields
        and SpecField.CODE_1C in exclude_fields
        and SpecField.ARTICLE not in exclude_fields
    ):
        negatives = _FIELD_NEGATIVES.get(SpecField.CODE_1C)
        if not (negatives and header_text in negatives):
            for synonym in COLUMN_SYNONYMS[SpecField.CODE_1C]:
                if _synonym_matches(header_text, synonym):
                    return SpecField.ARTICLE
    return None


def _score_row(
    row: Sequence[Any], *, exclude_fields: frozenset[SpecField] | None = None
) -> tuple[int, ColumnMapping]:
    """Считает header score для строки и одновременно строит маппинг."""
    mapping = ColumnMapping()
    score = 0
    article_candidates: list[int] = []
    for col_idx, cell in enumerate(row):
        text = _normalize_header_cell(cell)
        if not text:
            continue
        field = _match_field(text, exclude_fields=exclude_fields)
        if field is None:
            continue
        if field is SpecField.ARTICLE:
            article_candidates.append(col_idx)
        # Если поле уже занято — не перезаписываем (первое совпадение «побеждает»)
        if not mapping.has(field):
            mapping.columns[field] = col_idx
            score += 1

    # Фолбэк: если есть несколько ARTICLE-совпадений и нет NAME — второе
    # становится NAME. Покрывает кейс прайсов где «Артикул» и «Модель»
    # сосуществуют (Модель = описательное название продукта, не SKU).
    # Пример: Milwaukee — col 8 «Артикул» = 4933479867, col 9 «Модель» =
    # «Акк. ударная дрель/ш. M12 FPD2-0».
    if (
        not mapping.has(SpecField.NAME)
        and len(article_candidates) >= 2
        and (exclude_fields is None or SpecField.NAME not in exclude_fields)
    ):
        mapping.columns[SpecField.NAME] = article_candidates[1]
        score += 1

    return score, mapping


def detect_header(
    rows: Sequence[Sequence[Any]],
    *,
    max_scan_rows: int = 30,
    min_score: int = 2,
    exclude_fields: frozenset[SpecField] | None = None,
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
        score, mapping = _score_row(row, exclude_fields=exclude_fields)
        if score > best_score and mapping.has(SpecField.NAME):
            best_score = score
            best_row = idx
            best_mapping = mapping

    if best_row is None or best_mapping is None or best_score < min_score:
        return None

    return best_row, best_mapping
