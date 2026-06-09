"""Юнит-тесты адаптера SpecItem → MatchInput (без БД)."""

from fasttender.models import SpecItem
from fasttender.services.matcher.adapters import match_input_from_spec_item


def _spec_item(**kw: object) -> SpecItem:
    base: dict[str, object] = {
        "line_number": 1,
        "name_raw": "Болт",
        "article_raw": None,
        "manufacturer_raw": None,
        "attributes_raw": None,
        "unit_raw": None,
        "raw_row": {},
    }
    base.update(kw)
    return SpecItem(**base)


def test_attributes_folded_into_search_text_not_display_name() -> None:
    si = _spec_item(name_raw="Болт", attributes_raw="М10х40 DIN933")
    mi = match_input_from_spec_item(si)
    # Отображаемое имя — чистое
    assert mi.name == "Болт"
    # А текст поиска включает характеристики (нормализованные)
    assert mi.name_normalized is not None
    assert "din933" in mi.name_normalized
    assert "м10х40" in mi.name_normalized


def test_no_attributes_keeps_plain_name() -> None:
    si = _spec_item(name_raw="Гайка М10", attributes_raw=None)
    mi = match_input_from_spec_item(si)
    assert mi.name_normalized == "гайка м10"


def test_article_candidates_extracted_from_attributes() -> None:
    # Артикула нет, но в характеристиках — модель/код
    si = _spec_item(name_raw="Пылесос Einhell", attributes_raw="модель TE-VC 2340 SA 2342380")
    mi = match_input_from_spec_item(si)
    assert any("2342380" in c for c in mi.article_candidates)


def test_code_tokens_from_name_and_attributes() -> None:
    si = _spec_item(name_raw="Домкрат гидравлический бутылочный", attributes_raw="5т Д1-3913010-50 ШААЗ")
    mi = match_input_from_spec_item(si)
    assert "3913010" in mi.code_tokens
