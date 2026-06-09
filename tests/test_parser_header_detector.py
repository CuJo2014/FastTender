"""Тесты автоопределения шапки и маппинга колонок."""

from fasttender.services.parser.header_detector import detect_header
from fasttender.services.parser.types import SpecField


def test_simple_header_on_first_row() -> None:
    rows = [
        ["Наименование", "Артикул", "Кол-во", "Ед. изм.", "Цена"],
        ["Болт М10", "BLT-001", 10, "шт", 12.5],
    ]
    result = detect_header(rows)
    assert result is not None
    header_row, mapping = result
    assert header_row == 0
    assert mapping.get(SpecField.NAME) == 0
    assert mapping.get(SpecField.ARTICLE) == 1
    assert mapping.get(SpecField.QUANTITY) == 2
    assert mapping.get(SpecField.UNIT) == 3
    assert mapping.get(SpecField.PRICE) == 4


def test_header_not_on_first_row() -> None:
    """Реальная ситуация: логотип/реквизиты в первых строках, шапка — на 5-й."""
    rows = [
        ["ООО Ромашка", None, None, None],
        ["Спецификация №42", None, None, None],
        ["от 15.05.2026", None, None, None],
        [None, None, None, None],
        ["Наименование", "Артикул", "Количество", "Цена"],
        ["Болт М10", "BLT-001", 10, 12.5],
        ["Гайка М10", "NUT-001", 20, 5.0],
    ]
    result = detect_header(rows)
    assert result is not None
    header_row, mapping = result
    assert header_row == 4
    assert mapping.get(SpecField.NAME) == 0


def test_columns_in_arbitrary_order() -> None:
    rows = [
        ["Цена", "Артикул", "Производитель", "Наименование", "Кол-во"],
        [12.5, "BLT-001", "KOELNER", "Болт М10", 10],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.PRICE) == 0
    assert mapping.get(SpecField.ARTICLE) == 1
    assert mapping.get(SpecField.MANUFACTURER) == 2
    assert mapping.get(SpecField.NAME) == 3
    assert mapping.get(SpecField.QUANTITY) == 4


def test_synonyms_and_compound_headers() -> None:
    """Составные заголовки типа «Артикул товара» и синонимы «Номенклатура»."""
    rows = [
        ["Номенклатура", "Артикул товара", "К-во", "Ед.изм"],
        ["Болт", "B1", 5, "шт"],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.has(SpecField.NAME)
    assert mapping.has(SpecField.ARTICLE)
    assert mapping.has(SpecField.QUANTITY)
    assert mapping.has(SpecField.UNIT)


def test_no_header_returns_none() -> None:
    """Если в первых строках нет узнаваемых заголовков — None (требуется ручной маппинг)."""
    rows = [
        ["foo", "bar", "baz"],
        ["abc", "def", 123],
        ["xyz", "qwe", 456],
    ]
    result = detect_header(rows)
    assert result is None


def test_below_min_score_returns_none() -> None:
    """Только одна узнаваемая колонка — недостаточно для уверенного определения."""
    rows = [
        ["Наименование", "foo", "bar"],
        ["Болт", "abc", "def"],
    ]
    # min_score по умолчанию = 2
    assert detect_header(rows) is None


def test_english_headers() -> None:
    rows = [
        ["Name", "Article", "Quantity", "Unit", "Price"],
        ["Bolt M10", "BLT-001", 10, "pcs", 12.5],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.NAME) == 0
    assert mapping.get(SpecField.ARTICLE) == 1


def test_tnved_not_recognized_as_code_1c() -> None:
    """«Код ТНВЭД» — таможенный код, не должен попадать в CODE_1C
    (иначе dedupe схлопывает разные товары с одинаковым ТНВЭД)."""
    rows = [
        ["Наименование", "Модель", "Цена", "Код ТНВЭД"],
        ["Дрель", "BD-100", 1000, "8467210000"],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.NAME) == 0
    assert mapping.get(SpecField.ARTICLE) == 1  # «Модель»
    assert mapping.get(SpecField.PRICE) == 2
    # Главное: ТНВЭД НЕ попал в CODE_1C
    assert mapping.get(SpecField.CODE_1C) is None


def test_barcode_not_recognized_as_code_1c() -> None:
    rows = [
        ["Артикул", "Наименование", "Цена", "Штрих-код"],
        ["A-1", "Товар", 100, "4607000123456"],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.CODE_1C) is None


def test_article_and_model_coexist_model_becomes_name() -> None:
    """Когда в шапке есть и «Артикул» и «Модель»: Артикул → ARTICLE,
    Модель → NAME (как описательное название продукта).

    Реальный кейс: Milwaukee — col «Артикул» = 4933479867, col «Модель» =
    «Акк. ударная дрель/ш. M12 FPD2-0».
    """
    rows = [
        ["Категория", "Производитель", "Артикул", "Модель", "Цена"],
        ["Инструмент", "Milwaukee", "4933479867", "Акк. дрель M12", 27590],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.ARTICLE) == 2  # «Артикул»
    assert mapping.get(SpecField.NAME) == 3  # «Модель» → fallback NAME
    assert mapping.get(SpecField.PRICE) == 4


def test_only_model_still_becomes_article() -> None:
    """Если в шапке только «Модель» (без «Артикул») — она article, как для MKT."""
    rows = [
        ["Категория", "Модель", "Наименование", "Цена"],
        ["Инструмент", "BD-100", "Дрель", 1000],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.ARTICLE) == 1  # «Модель» — единственный кандидат
    assert mapping.get(SpecField.NAME) == 2  # NAME уже найден явно


def test_exclude_fields_skips_code_1c_entirely() -> None:
    """Когда CODE_1C в exclude_fields — колонка «Код» НЕ попадёт в маппинг,
    даже если она явно так названа. Используется для прайсов поставщиков —
    у них не бывает Кода 1С (это идентификатор каталога компании).
    """
    rows = [
        ["Артикул", "Код", "Наименование", "Цена"],
        ["A-1", "12345", "Болт", 10],
    ]
    result = detect_header(rows, exclude_fields=frozenset({SpecField.CODE_1C}))
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.ARTICLE) == 0
    assert mapping.get(SpecField.CODE_1C) is None  # принудительно исключён
    assert mapping.get(SpecField.NAME) == 2


def test_sku_in_parens_matches_article() -> None:
    """«Код товара (SKU)» — частый заголовок в прайсах поставщиков.
    Раньше «sku» не ловилось из-за того что скобки ломали word boundary."""
    rows = [
        ["Наименование", "Код товара (SKU)", "Цена"],
        ["Болт", "ABC-001", 100],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.ARTICLE) == 1


def test_kod_tovara_alone_matches_article_in_pricelist() -> None:
    """«Код товара» (без SKU) теперь матчится как ARTICLE.
    Для прайсов это удобно — у каталога CODE_1C приоритетнее (priority order)."""
    rows = [
        ["Наименование", "Код товара", "Цена"],
        ["Болт", "ABC-001", 100],
    ]
    result = detect_header(rows, exclude_fields=frozenset({SpecField.CODE_1C}))
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.ARTICLE) == 1


def test_unit_with_trailing_period() -> None:
    """«Ед.изм.» (с точкой в конце) — частый формат."""
    rows = [
        ["Артикул", "Наименование", "Ед.изм.", "Цена"],
        ["A-1", "Болт", "шт", 100],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.UNIT) == 2


def test_real_code_1c_still_recognized() -> None:
    """Колонка «Код» (без квалификатора) по-прежнему попадает в CODE_1C —
    это типичный заголовок 1С-выгрузок."""
    rows = [
        ["Артикул", "Код", "Наименование", "Цена"],
        ["A-1", "Ц0000000100", "Болт", 10],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.CODE_1C) == 1


def test_kod_becomes_article_in_pricelist() -> None:
    """В прайсе поставщика (CODE_1C исключён) колонка «Код» = их артикул.
    Регрессия RUI: без этого позиции без артикула не матчатся при ре-импорте."""
    rows = [
        ["Код", "Наименование", "Цена без НДС", "Количество"],
        ["ri.377.20", "Борфреза", 931, 81],
    ]
    result = detect_header(rows, exclude_fields=frozenset({SpecField.CODE_1C}))
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.ARTICLE) == 0
    assert mapping.get(SpecField.CODE_1C) is None


def test_kod_stays_code_1c_without_exclude() -> None:
    """Без исключения CODE_1C (каталог) «Код» остаётся CODE_1C, не ARTICLE."""
    rows = [
        ["Код", "Наименование", "Цена"],
        ["Ц0000000100", "Болт", 10],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.CODE_1C) == 0
    assert mapping.get(SpecField.ARTICLE) is None


def test_barcode_not_promoted_to_article_in_pricelist() -> None:
    """«Штрих-код» — negative-list CODE_1C: НЕ должен стать ARTICLE в прайсе."""
    rows = [
        ["Штрих-код", "Наименование", "Цена"],
        ["4600000000017", "Болт", 10],
    ]
    result = detect_header(rows, exclude_fields=frozenset({SpecField.CODE_1C}))
    # NAME есть, но article не назначается из штрих-кода
    if result is not None:
        _, mapping = result
        assert mapping.get(SpecField.ARTICLE) is None


def test_catalog_keeps_both_article_and_kod() -> None:
    """Каталог 1С: «Артикул» → ARTICLE, «Код» → CODE_1C (оба сохраняются)."""
    rows = [
        ["Артикул", "Код", "Наименование", "Цена"],
        ["BLT-1", "Ц0000000100", "Болт", 10],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.ARTICLE) == 0
    assert mapping.get(SpecField.CODE_1C) == 1


def test_attributes_column_detected() -> None:
    """Колонка «Характеристики» → SpecField.ATTRIBUTES."""
    rows = [
        ["Наименование", "Характеристики", "Кол-во", "Ед. изм."],
        ["Болт", "М10х40, DIN933, оцинк.", 10, "шт"],
    ]
    result = detect_header(rows)
    assert result is not None
    _, mapping = result
    assert mapping.get(SpecField.NAME) == 0
    assert mapping.get(SpecField.ATTRIBUTES) == 1


def test_attributes_synonyms_variants() -> None:
    for header in (
        "Характеристика",
        "Технические характеристики",
        "Тех. характеристики",
        "Параметры",
        "Параметры подбора",
        "Свойства",
    ):
        rows = [["Наименование", header, "Кол-во"], ["x", "y", 1]]
        result = detect_header(rows)
        assert result is not None, header
        _, mapping = result
        assert mapping.get(SpecField.ATTRIBUTES) == 1, header


def test_attributes_extracted_into_parsed_item() -> None:
    """build_result кладёт значение колонки характеристик в ParsedItem.attributes."""
    from fasttender.services.parser._matrix import build_result

    matrix = [
        ["Наименование", "Характеристики", "Кол-во"],
        ["Болт", "М10х40 DIN933 оцинкованный", 10],
    ]
    res = build_result(matrix)
    assert len(res.items) == 1
    assert res.items[0].attributes == "М10х40 DIN933 оцинкованный"


def test_trademark_synonyms_map_to_manufacturer() -> None:
    for header in ("Торговая марка", "ТМ", "Товарный знак", "Производитель", "Бренд"):
        rows = [["Артикул", "Наименование", header, "Цена"], ["A1", "Болт", "KOELNER", 10]]
        result = detect_header(rows)
        assert result is not None, header
        _, mapping = result
        assert mapping.get(SpecField.MANUFACTURER) == 2, header
