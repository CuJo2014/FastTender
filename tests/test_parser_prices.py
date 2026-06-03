"""Тесты заполнения ParsedItem.prices и проекции preferred в price.

Проверяет интеграцию detect_price_columns → _matrix: несколько цен на
позицию извлекаются в .prices, основная (.price) — preferred (net>gross),
а при нераспознанных заголовках работает fallback на mapped-колонку.
"""

from decimal import Decimal

from fasttender.services.parser._matrix import build_result
from fasttender.services.parser.price_columns import select_preferred
from fasttender.services.parser.types import (
    ColumnMapping,
    PriceEntry,
    SpecField,
    VatBasis,
)

# --- select_preferred ---


def test_preferred_prefers_net_over_gross() -> None:
    prices = [
        PriceEntry(amount=Decimal("120"), vat=VatBasis.GROSS),
        PriceEntry(amount=Decimal("100"), vat=VatBasis.NET),
    ]
    assert select_preferred(prices).amount == Decimal("100")


def test_preferred_falls_back_to_gross_when_no_net() -> None:
    """SMT-кейс: обе колонки с НДС — берём первую gross (базовую, не «с ТЗР»)."""
    prices = [
        PriceEntry(amount=Decimal("10080"), vat=VatBasis.GROSS, label="Цена с НДС"),
        PriceEntry(amount=Decimal("12080"), vat=VatBasis.GROSS, label="ЦЕНА С НДС С ТЗР"),
    ]
    assert select_preferred(prices).amount == Decimal("10080")


def test_preferred_tie_break_is_column_order() -> None:
    """TEL-кейс: первый net (уровень «Цены с вашей скидкой») предпочтительнее
    последующих net (РРЦ/МИЦ)."""
    prices = [
        PriceEntry(amount=Decimal("8.85"), vat=VatBasis.GROSS, tier="Цены с вашей скидкой"),
        PriceEntry(amount=Decimal("7.26"), vat=VatBasis.NET, tier="Цены с вашей скидкой"),
        PriceEntry(amount=Decimal("12.52"), vat=VatBasis.NET, tier="РРЦ"),
    ]
    pref = select_preferred(prices)
    assert pref.amount == Decimal("7.26")
    assert pref.tier == "Цены с вашей скидкой"


def test_preferred_none_for_empty() -> None:
    assert select_preferred([]) is None


# --- build_result: prices populated + projected ---


def test_pair_populates_prices_and_projects_net() -> None:
    matrix = [
        ["Артикул", "Наименование", "Цена с НДС, руб.", "Цена без НДС, руб."],
        ["A-1", "Дрель", 27590, 22614.75],
    ]
    result = build_result(matrix)
    item = result.items[0]
    assert len(item.prices) == 2
    assert {p.vat for p in item.prices} == {VatBasis.NET, VatBasis.GROSS}
    # preferred = net
    assert item.price == Decimal("22614.75")


def test_single_price_column_unchanged_behaviour() -> None:
    """Один «Цена» (unknown НДС) — price как раньше, prices содержит её."""
    matrix = [["Артикул", "Наименование", "Цена"], ["A-1", "Болт", "12.50"]]
    result = build_result(matrix)
    item = result.items[0]
    assert item.price == Decimal("12.50")
    assert len(item.prices) == 1
    assert item.prices[0].vat is VatBasis.UNKNOWN


def test_fallback_to_mapped_column_when_headers_unrecognized() -> None:
    """Override-маппинг с нечитаемыми заголовками: ценовых колонок не
    распознано → prices пуст, price берётся из mapped PRICE-колонки."""
    matrix = [
        ["a", "b", "c"],  # заголовки-заглушки
        ["A-1", "Позиция", "50"],
    ]
    override = ColumnMapping(
        columns={SpecField.ARTICLE: 0, SpecField.NAME: 1, SpecField.PRICE: 2}
    )
    result = build_result(matrix, mapping_override=override)
    item = result.items[0]
    assert item.prices == []
    assert item.price == Decimal("50")


def test_sum_column_not_projected_as_price() -> None:
    """«Сумма» (итог) не считается ценой: prices берёт только юнит-цены."""
    matrix = [
        ["Артикул", "Наименование", "Цена без НДС", "Сумма (руб.)"],
        ["A-1", "Болт", 7.26, 726.0],
    ]
    result = build_result(matrix)
    item = result.items[0]
    assert [p.label for p in item.prices] == ["Цена без НДС"]
    assert item.price == Decimal("7.26")
