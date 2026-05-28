"""Интеграционные тесты Excel-парсера (XLSX)."""

from decimal import Decimal
from pathlib import Path

import pytest

from fasttender.services.parser import (
    ColumnMapping,
    ParseError,
    SpecField,
    SpecificationParser,
)
from tests.fixtures.spec_builders import make_xlsx


@pytest.fixture
def parser() -> SpecificationParser:
    return SpecificationParser()


def test_clean_xlsx(tmp_path: Path, parser: SpecificationParser) -> None:
    """Идеальный файл: шапка на первой строке, все поля заполнены."""
    path = make_xlsx(
        tmp_path / "clean.xlsx",
        rows=[
            ["Наименование", "Артикул", "Производитель", "Кол-во", "Ед. изм.", "Цена"],
            ["Болт М10х40 DIN933", "BLT-M10-040", "KOELNER", 50, "шт", 12.5],
            ["Гайка М10 DIN934", "NUT-M10", "KOELNER", 50, "шт", 4.2],
            ["Шайба М10", "WSH-M10", None, 100, "шт", 1.1],
        ],
    )

    result = parser.parse(path)
    assert result.items_count == 3
    assert result.header_row == 0
    assert result.warnings == []
    assert result.sheet_name == "Спецификация"

    first = result.items[0]
    assert first.line_number == 1
    assert first.name == "Болт М10х40 DIN933"
    assert first.article == "BLT-M10-040"
    assert first.manufacturer == "KOELNER"
    assert first.quantity == Decimal("50")
    assert first.unit == "шт"
    assert first.price == Decimal("12.5")


def test_xlsx_with_header_offset(tmp_path: Path, parser: SpecificationParser) -> None:
    """Реальный случай: реквизиты клиента в первых 4 строках, шапка на 5-й."""
    path = make_xlsx(
        tmp_path / "with_offset.xlsx",
        rows=[
            ["ООО Ромашка", None, None, None],
            ["ИНН 1234567890", None, None, None],
            ["Спецификация №42", None, None, None],
            [None, None, None, None],
            ["Наименование", "Артикул", "Количество", "Цена"],
            ["Болт М10", "BLT-001", 10, 12.5],
            ["Гайка М10", "NUT-001", 20, 5.0],
        ],
    )
    result = parser.parse(path)
    assert result.header_row == 4
    assert result.items_count == 2
    assert result.items[0].name == "Болт М10"


def test_xlsx_with_merged_cells(tmp_path: Path, parser: SpecificationParser) -> None:
    """Объединённые ячейки в шапке и в группирующей колонке."""
    path = make_xlsx(
        tmp_path / "merged.xlsx",
        rows=[
            ["Спецификация по группам", None, None, None],
            ["Наименование", "Артикул", "Кол-во", "Цена"],
            ["Крепёж", None, None, None],  # group header — будет проигнорирован (нет name?)
            ["Болт М10", "BLT-001", 10, 12.5],
            ["Гайка М10", "NUT-001", 20, 5.0],
        ],
        merged_ranges=["A1:D1"],
    )
    result = parser.parse(path)
    # «Крепёж» имеет name → попадает в items как line 1; это валидное поведение
    # парсера: фильтрация «названий-групп» — задача нормализатора/UI
    names = [item.name for item in result.items]
    assert "Болт М10" in names
    assert "Гайка М10" in names


def test_xlsx_with_dirty_numbers(tmp_path: Path, parser: SpecificationParser) -> None:
    """Числа как текст: «≈10», «10 шт», «10-12». Парсер должен извлечь левую границу."""
    path = make_xlsx(
        tmp_path / "dirty.xlsx",
        rows=[
            ["Наименование", "Артикул", "Кол-во", "Цена"],
            ["Болт М10", "BLT-001", "≈10", "12,5"],
            ["Гайка М10", "NUT-001", "20 шт", "по запросу"],
            ["Шайба М10", "WSH-M10", "10-15", "1.1"],
        ],
    )
    result = parser.parse(path)
    assert result.items_count == 3
    assert result.items[0].quantity == Decimal("10")
    assert result.items[0].price == Decimal("12.5")
    assert result.items[1].quantity == Decimal("20")
    # «по запросу» — warning, цена остаётся None
    assert result.items[1].price is None
    assert any(w.field == SpecField.PRICE and w.line_number == 2 for w in result.warnings)
    assert result.items[2].quantity == Decimal("10")  # левая граница интервала


def test_xlsx_no_header_raises(tmp_path: Path, parser: SpecificationParser) -> None:
    path = make_xlsx(
        tmp_path / "no_header.xlsx",
        rows=[
            ["foo", "bar", "baz"],
            ["abc", "def", 123],
        ],
    )
    with pytest.raises(ParseError, match="шапк"):
        parser.parse(path)


def test_xlsx_mapping_override(tmp_path: Path, parser: SpecificationParser) -> None:
    """Когда автоопределение не справилось — менеджер указывает колонки вручную."""
    path = make_xlsx(
        tmp_path / "no_header.xlsx",
        rows=[
            ["foo", "bar", "baz", "qux"],
            ["Болт М10", "BLT-001", 10, 12.5],
        ],
    )
    mapping = ColumnMapping(
        columns={
            SpecField.NAME: 0,
            SpecField.ARTICLE: 1,
            SpecField.QUANTITY: 2,
            SpecField.PRICE: 3,
        }
    )
    result = parser.parse(path, mapping_override=mapping)
    assert result.items_count == 1
    assert result.items[0].name == "Болт М10"
    assert result.items[0].quantity == Decimal("10")


def test_empty_lines_are_skipped(tmp_path: Path, parser: SpecificationParser) -> None:
    path = make_xlsx(
        tmp_path / "with_gaps.xlsx",
        rows=[
            ["Наименование", "Артикул", "Кол-во", "Цена"],
            ["Болт М10", "BLT-001", 10, 12.5],
            [None, None, None, None],
            ["", "", "", ""],
            ["Гайка М10", "NUT-001", 20, 5.0],
        ],
    )
    result = parser.parse(path)
    # line_number — последовательная, пропуски пустых не учитываются
    assert [i.line_number for i in result.items] == [1, 2]
    assert [i.name for i in result.items] == ["Болт М10", "Гайка М10"]


def test_unsupported_extension(tmp_path: Path, parser: SpecificationParser) -> None:
    path = tmp_path / "file.pdf"
    path.write_bytes(b"%PDF-1.4")
    with pytest.raises(ParseError, match="Неподдерживаемое расширение"):
        parser.parse(path)
