"""Тесты детектора ценовых колонок (несколько цен на позицию + net/gross).

Шапки синтетические, но повторяют структуру реальных прайсов поставщиков
(файлы в docs/pricelists/ не коммитятся — коммерческие данные). Соответствие
реальным файлам проверено вручную 2026-06-02, см.
fasttender-price-storage-decisions.
"""

from fasttender.services.parser.price_columns import (
    VatBasis,
    detect_price_columns,
)


def _by_index(cols):
    return {c.col_index: c for c in cols}


def test_pair_net_and_gross_both_returned() -> None:
    """MIL: «Цена с НДС» + «Цена без НДС» рядом — возвращаются ОБЕ."""
    rows = [
        ["Артикул", "Модель", "Цена с НДС, руб.", "Цена без НДС, руб."],
        ["4933479867", "Дрель M12", 27590, 22614.75],
    ]
    cols = detect_price_columns(rows, header_row_index=0)
    assert len(cols) == 2
    by = _by_index(cols)
    assert by[2].vat is VatBasis.GROSS
    assert by[3].vat is VatBasis.NET


def test_single_unknown_vat() -> None:
    """INT: одна колонка «Цена, руб» без указания НДС → unknown."""
    rows = [["Артикул", "Наименование", "Цена, руб"], ["A-1", "Болт", 166.5]]
    cols = detect_price_columns(rows, header_row_index=0)
    assert len(cols) == 1
    assert cols[0].col_index == 2
    assert cols[0].vat is VatBasis.UNKNOWN


def test_sum_column_is_not_a_price() -> None:
    """AKR: «Сумма (руб.)» — итог по строке, НЕ юнит-цена; не попадает."""
    rows = [
        ["Артикул", "Цена за ед. (без НДС)", "Цена за ед. (с НДС)", "Сумма (руб.)"],
        ["A-1", 7.26, 8.85, 885.0],
    ]
    cols = detect_price_columns(rows, header_row_index=0)
    assert [c.col_index for c in cols] == [1, 2]
    by = _by_index(cols)
    assert by[1].vat is VatBasis.NET
    assert by[2].vat is VatBasis.GROSS


def test_vat_rate_column_excluded() -> None:
    """«Ставка НДS, %» не должна считаться ценой, хотя содержит «НДС»."""
    rows = [["Артикул", "Цена с НДС", "Ставка НДС, %"], ["A-1", 100, 22]]
    cols = detect_price_columns(rows, header_row_index=0)
    assert [c.col_index for c in cols] == [1]


def test_three_columns_rrc_net_promo() -> None:
    """MKT: РРЦ с НДС + Цена без НДС + Цена по акции без НДС — все три."""
    rows = [
        [
            "Модель",
            "РРЦ с НДС, руб",
            "Цена без НДС, руб",
            "Цена по акции без НДС, руб",
        ],
        ["UB100DZ", 5073, 3589, 3400],
    ]
    cols = detect_price_columns(rows, header_row_index=0)
    by = _by_index(cols)
    assert set(by) == {1, 2, 3}
    assert by[1].vat is VatBasis.GROSS
    assert by[2].vat is VatBasis.NET
    assert by[3].vat is VatBasis.NET


def test_english_headers_milwaukee() -> None:
    """MIL EN-шапка: «SSP w/ VAT» / «SSP w/o VAT»."""
    rows = [["Material", "SSP  w/ VAT [RUB]", "SSP  w/o VAT [RUB]"], ["x", 1, 2]]
    cols = detect_price_columns(rows, header_row_index=0)
    by = _by_index(cols)
    assert by[1].vat is VatBasis.GROSS
    assert by[2].vat is VatBasis.NET


def test_bare_vat_labels_with_tiers_tel() -> None:
    """TEL: заголовок цены — просто «c НДС»/«без НДС», а уровень («Цены с
    вашей скидкой»/«РРЦ»/«МИЦ») — в строке НАД шапкой (3 пары)."""
    group = [None] * 11 + ["Цены с вашей скидкой", None, "РРЦ", None, "МИЦ", None]
    header = ["Код товара (SKU)", "Наименование"] + [None] * 9 + [
        "c НДС",
        "без НДС",
        "c НДС",
        "без НДС",
        "c НДС",
        "без НДС",
    ]
    rows = [group, header, ["78595", "Наконечник"] + [None] * 9 + [8.85, 7.26, 15.27, 12.52, 12.98, 10.64]]
    cols = detect_price_columns(rows, header_row_index=1)
    assert len(cols) == 6
    by = _by_index(cols)
    # пары верно классифицированы по НДС
    assert by[11].vat is VatBasis.GROSS and by[12].vat is VatBasis.NET
    assert by[13].vat is VatBasis.GROSS and by[14].vat is VatBasis.NET
    assert by[15].vat is VatBasis.GROSS and by[16].vat is VatBasis.NET
    # уровни протянуты из группирующей строки
    assert by[11].tier == "Цены с вашей скидкой"
    assert by[12].tier == "Цены с вашей скидкой"
    assert by[13].tier == "РРЦ"
    assert by[15].tier == "МИЦ"


def test_noise_above_header_not_treated_as_tier() -> None:
    """Если над шапкой не группа, а примечание — один и тот же ярлык
    протягивается на все цены; такой «уровень» — шум, отбрасываем."""
    rows = [
        ["Красным выделена изменившаяся цена", None, None],
        ["Модель", "Цена с НДС", "Цена без НДС"],
        ["x", 100, 82],
    ]
    cols = detect_price_columns(rows, header_row_index=1)
    assert all(c.tier is None for c in cols)


def test_no_price_columns() -> None:
    rows = [["Артикул", "Наименование", "Кол-во"], ["A-1", "Болт", 10]]
    assert detect_price_columns(rows, header_row_index=0) == []
