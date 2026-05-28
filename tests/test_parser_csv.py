"""Тесты CSV/TSV-парсера: разные кодировки и разделители."""

from decimal import Decimal
from pathlib import Path

import pytest

from fasttender.services.parser import ParseError, SpecificationParser
from tests.fixtures.spec_builders import make_csv


@pytest.fixture
def parser() -> SpecificationParser:
    return SpecificationParser()


def test_utf8_comma(tmp_path: Path, parser: SpecificationParser) -> None:
    path = make_csv(
        tmp_path / "spec.csv",
        rows=[
            ["Наименование", "Артикул", "Кол-во", "Цена"],
            ["Болт М10", "BLT-001", "10", "12.5"],
            ["Гайка М10", "NUT-001", "20", "5.0"],
        ],
        encoding="utf-8",
        delimiter=",",
    )
    result = parser.parse(path)
    assert result.encoding == "utf-8"
    assert result.delimiter == ","
    assert result.items_count == 2
    assert result.items[0].quantity == Decimal("10")


def test_cp1251_semicolon(tmp_path: Path, parser: SpecificationParser) -> None:
    """Самый частый формат для русских поставщиков: cp1251 + точка с запятой."""
    path = make_csv(
        tmp_path / "spec_cp1251.csv",
        rows=[
            ["Наименование", "Артикул", "Кол-во", "Цена"],
            ["Болт М10", "BLT-001", "10", "12,5"],
            ["Гайка М10", "NUT-001", "20", "5,0"],
        ],
        encoding="cp1251",
        delimiter=";",
    )
    result = parser.parse(path)
    assert result.encoding == "cp1251"
    assert result.delimiter == ";"
    assert result.items_count == 2
    assert result.items[0].price == Decimal("12.5")


def test_tsv(tmp_path: Path, parser: SpecificationParser) -> None:
    path = make_csv(
        tmp_path / "spec.tsv",
        rows=[
            ["Наименование", "Артикул", "Кол-во"],
            ["Болт М10", "BLT-001", "10"],
        ],
        encoding="utf-8",
        delimiter="\t",
    )
    result = parser.parse(path)
    assert result.delimiter == "\t"
    assert result.items_count == 1


def test_encoding_override(tmp_path: Path, parser: SpecificationParser) -> None:
    """Если chardet ошибся, override обязан помочь."""
    path = make_csv(
        tmp_path / "tricky.csv",
        rows=[
            ["Наименование", "Артикул", "Кол-во"],
            ["Болт М10", "BLT-001", "10"],
        ],
        encoding="cp1251",
        delimiter=";",
    )
    result = parser.parse(path, encoding_override="cp1251", delimiter_override=";")
    assert result.encoding == "cp1251"
    assert result.items[0].name == "Болт М10"


def test_empty_csv(tmp_path: Path, parser: SpecificationParser) -> None:
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    with pytest.raises(ParseError, match="пуст"):
        parser.parse(path)


def test_bom_utf8(tmp_path: Path, parser: SpecificationParser) -> None:
    """Excel часто сохраняет CSV с BOM."""
    path = tmp_path / "with_bom.csv"
    content = "Наименование,Артикул,Кол-во\nБолт,BLT-001,10\n"
    path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    result = parser.parse(path)
    assert result.items_count == 1
    # BOM не должен попасть в первый заголовок
    assert result.items[0].name == "Болт"
