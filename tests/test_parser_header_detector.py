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
