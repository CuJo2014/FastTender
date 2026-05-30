"""Unit-тесты на конфигурируемые трансформации ParsedItem."""

from decimal import Decimal

import pytest

from fasttender.services.importer.transformations import (
    SupplierTransformations,
    apply_transformations,
)
from fasttender.services.parser import ParsedItem


def _item(**overrides) -> ParsedItem:
    base = dict(line_number=1, name="Тестовая позиция", price=Decimal("100"))
    base.update(overrides)
    return ParsedItem(**base)


# --- Конфиг ---


def test_default_config_is_noop() -> None:
    cfg = SupplierTransformations()
    assert cfg.is_noop


def test_brand_regex_must_have_two_groups() -> None:
    with pytest.raises(ValueError, match="2 группы"):
        SupplierTransformations(brand_regex=r"^(.+)$")  # одна группа


def test_brand_regex_invalid_syntax_rejected() -> None:
    with pytest.raises(ValueError, match="Невалидный"):
        SupplierTransformations(brand_regex=r"^(.+)$[")


def test_brand_regex_empty_string_treated_as_none() -> None:
    cfg = SupplierTransformations(brand_regex="")
    assert cfg.brand_regex is None


def test_from_meta_handles_missing_or_broken_config() -> None:
    assert SupplierTransformations.from_meta(None).is_noop
    assert SupplierTransformations.from_meta({}).is_noop
    assert SupplierTransformations.from_meta({"transformations": None}).is_noop
    # сломанный конфиг → дефолтный (не падаем)
    assert SupplierTransformations.from_meta(
        {"transformations": {"brand_regex": "[broken"}}
    ).is_noop


# --- brand_regex ---


def test_brand_extracted_from_name_when_manufacturer_empty() -> None:
    cfg = SupplierTransformations(brand_regex=r"^(.+?)\s*//\s*(.+?)\s*$")
    items = [_item(name="Молоток слесарный 200 г // Sparta")]
    out = apply_transformations(items, cfg)
    assert out[0].name == "Молоток слесарный 200 г"
    assert out[0].manufacturer == "Sparta"


def test_brand_regex_not_applied_when_manufacturer_already_set() -> None:
    cfg = SupplierTransformations(brand_regex=r"^(.+?)\s*//\s*(.+?)\s*$")
    items = [_item(name="Молоток // Sparta", manufacturer="ЗАВОД")]
    out = apply_transformations(items, cfg)
    assert out[0].name == "Молоток // Sparta"  # не тронули
    assert out[0].manufacturer == "ЗАВОД"


def test_brand_regex_no_match_leaves_item_alone() -> None:
    cfg = SupplierTransformations(brand_regex=r"^(.+?)\s*//\s*(.+?)\s*$")
    items = [_item(name="Молоток без бренда")]
    out = apply_transformations(items, cfg)
    assert out[0].name == "Молоток без бренда"
    assert out[0].manufacturer is None


# --- НДС ---


def test_vat_excluded_from_price() -> None:
    cfg = SupplierTransformations(vat_included=True, vat_rate=20)
    items = [_item(price=Decimal("120"))]
    out = apply_transformations(items, cfg)
    assert out[0].price == Decimal("100.0000")


def test_vat_with_custom_rate() -> None:
    cfg = SupplierTransformations(vat_included=True, vat_rate=10)
    items = [_item(price=Decimal("110"))]
    out = apply_transformations(items, cfg)
    assert out[0].price == Decimal("100.0000")


def test_vat_skipped_when_price_is_none() -> None:
    cfg = SupplierTransformations(vat_included=True, vat_rate=20)
    items = [_item(price=None)]
    out = apply_transformations(items, cfg)
    assert out[0].price is None


# --- Дефолты ---


def test_default_unit_filled_only_when_empty() -> None:
    cfg = SupplierTransformations(default_unit="шт")
    items = [_item(unit=None), _item(unit="кг")]
    out = apply_transformations(items, cfg)
    assert out[0].unit == "шт"
    assert out[1].unit == "кг"  # явно заданное не перезаписываем


def test_default_currency_filled_only_when_empty() -> None:
    cfg = SupplierTransformations(default_currency="RUB")
    items = [_item(currency=None), _item(currency="USD")]
    out = apply_transformations(items, cfg)
    assert out[0].currency == "RUB"
    assert out[1].currency == "USD"


# --- Композиция ---


def test_all_transformations_compose() -> None:
    cfg = SupplierTransformations(
        brand_regex=r"^(.+?)\s*//\s*(.+?)\s*$",
        vat_included=True,
        vat_rate=20,
        default_unit="шт",
        default_currency="RUB",
    )
    items = [_item(name="Болт М10 // Sparta", price=Decimal("120"))]
    out = apply_transformations(items, cfg)
    assert out[0].name == "Болт М10"
    assert out[0].manufacturer == "Sparta"
    assert out[0].price == Decimal("100.0000")
    assert out[0].unit == "шт"
    assert out[0].currency == "RUB"


def test_manufacturer_force_overrides_file_value() -> None:
    """force-manufacturer перетирает то что было определено парсером,
    в отличие от default_unit/default_currency (только пустые)."""
    cfg = SupplierTransformations(manufacturer="Milwaukee")
    items = [
        _item(manufacturer="FUEL™"),  # уже есть значение
        _item(manufacturer=None),  # пусто
    ]
    out = apply_transformations(items, cfg)
    assert out[0].manufacturer == "Milwaukee"  # перетёрто
    assert out[1].manufacturer == "Milwaukee"  # заполнено


def test_manufacturer_only_makes_config_non_noop() -> None:
    cfg = SupplierTransformations(manufacturer="Makita")
    assert not cfg.is_noop


def test_noop_returns_same_list() -> None:
    cfg = SupplierTransformations()
    items = [_item()]
    out = apply_transformations(items, cfg)
    assert out is items  # дешёвый short-circuit
