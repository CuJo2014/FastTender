"""Unit-тесты нормализации значений ячеек."""

from decimal import Decimal

import pytest

from fasttender.services.parser.value_normalizer import (
    clean_string,
    normalize_article,
    normalize_name,
    parse_decimal,
    parse_int,
)


class TestCleanString:
    def test_none_returns_none(self) -> None:
        assert clean_string(None) is None

    def test_empty_returns_none(self) -> None:
        assert clean_string("") is None
        assert clean_string("   ") is None

    def test_strips_nbsp(self) -> None:
        assert clean_string("болт\xa0М10") == "болт М10"

    def test_collapses_whitespace(self) -> None:
        assert clean_string("  болт   \n М10  ") == "болт М10"

    def test_passes_through_int(self) -> None:
        assert clean_string(42) == "42"


class TestNormalizeArticle:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("blt-m10-040-zn", "BLTM10040ZN"),
            ("М10*40", "М1040"),
            ("ABC.123/45", "ABC12345"),
            ("  a-b-c  ", "ABC"),
            ("", None),
            (None, None),
        ],
    )
    def test_normalization(self, raw: str | None, expected: str | None) -> None:
        assert normalize_article(raw) == expected


class TestNormalizeName:
    def test_lowercase_and_clean(self) -> None:
        assert normalize_name("Болт М10×40 DIN933") == "болт м10×40 din933"

    def test_empty(self) -> None:
        assert normalize_name("") is None


class TestParseDecimal:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (10, Decimal("10")),
            (10.5, Decimal("10.5")),
            ("10", Decimal("10")),
            ("10.5", Decimal("10.5")),
            ("10,5", Decimal("10.5")),  # десятичная запятая
            ("1 234,5", Decimal("1234.5")),  # разделитель тысяч
            ("1\xa0234,5", Decimal("1234.5")),  # NBSP как разделитель тысяч
            ("≈10", Decimal("10")),  # приблизительно
            ("10 шт", Decimal("10")),  # с единицей
            ("10-12", Decimal("10")),  # интервал — берём левую
            ("по запросу", None),  # совсем не число
            (None, None),
            ("", None),
            (True, None),  # bool — не число для домена
        ],
    )
    def test_parse(self, raw: object, expected: Decimal | None) -> None:
        assert parse_decimal(raw) == expected


class TestParseInt:
    def test_round_trip(self) -> None:
        assert parse_int("10,5") == 10
        assert parse_int("10") == 10
        assert parse_int("ничего") is None
