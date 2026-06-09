"""Unit-тесты нормализации значений ячеек."""

from decimal import Decimal

import pytest

from fasttender.services.parser.value_normalizer import (
    clean_string,
    extract_article_candidates,
    normalize_article,
    normalize_name,
    parse_decimal,
    parse_int,
)


class TestExtractArticleCandidates:
    def test_long_numeric_sku_extracted(self) -> None:
        # «Tarkett 91928» — 91928 это SKU (≥5 цифр)
        assert "91928" in extract_article_candidates("Шнур для сварки ПВХ 4мм Tarkett 91928")

    def test_alphanumeric_model_extracted(self) -> None:
        cands = extract_article_candidates("Пылесос Einhell TE-VC 2340 SA 2342380")
        assert "2342380" in cands  # длинный SKU (≥5 цифр)
        # «TE-VC» без цифры и «2340» (4 цифры) — консервативно НЕ берём
        assert "TEVC" not in cands

    def test_alphanumeric_with_digit_extracted(self) -> None:
        # токен с буквами И цифрой («КЭВ-32M3») — это модель
        cands = extract_article_candidates("Тепловентилятор КЭВ-32M3")
        assert "КЭВ32M3" in cands

    def test_dimensions_not_extracted(self) -> None:
        # «200мм», «4мм» — размерности, не артикулы
        assert extract_article_candidates("Плоскогубцы комбинированные 200мм") == []
        assert extract_article_candidates("Кабель 4мм сечение") == []

    def test_short_pure_number_not_extracted(self) -> None:
        # короткое число (<5 цифр) без букв — это размер/количество
        assert extract_article_candidates("Уголок 250 штук") == []

    def test_pure_text_no_candidates(self) -> None:
        assert extract_article_candidates("Штангенциркуль металлический") == []
        assert extract_article_candidates("") == []
        assert extract_article_candidates(None) == []

    def test_dedup_and_order(self) -> None:
        cands = extract_article_candidates("Деталь M12 крепёж M12 модель ABC123")
        assert cands == ["M12", "ABC123"]  # уникальные, в порядке появления


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
            ("1234", Decimal("1234")),  # 4+ цифр без разделителя (был баг → 123)
            ("12345", Decimal("12345")),
            ("1,234.56", Decimal("1234.56")),  # US: «,» тысячи, «.» десятичная
            ("1.234,56", Decimal("1234.56")),  # EU: «.» тысячи, «,» десятичная
            ("1,234,567", Decimal("1234567")),  # несколько запятых → тысячи
            ("-10", Decimal("-10")),  # знак
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


def test_extract_code_tokens_digit_runs() -> None:
    from fasttender.services.parser.value_normalizer import extract_code_tokens

    assert extract_code_tokens("5т Д1-3913010-50 ШААЗ") == ["3913010"]
    # короткие числа (тоннаж/размер) отбрасываются
    assert extract_code_tokens("Домкрат 30т бутылочный") == []
    # несколько серий, уникальность и порядок
    assert extract_code_tokens("модель TE-VC 2342380 и 100500") == ["2342380", "100500"]
    assert extract_code_tokens(None) == []
