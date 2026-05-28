"""ORM-аdapters для матчера.

Здесь — единственное место, где `MatchInput` встречается с ORM-моделями.
Это исключает циклические импорты в `types.py`.
"""

from fasttender.models import SpecItem
from fasttender.services.matcher.types import MatchInput
from fasttender.services.parser.value_normalizer import (
    normalize_article,
    normalize_name,
)


def match_input_from_spec_item(spec_item: SpecItem) -> MatchInput:
    """Превращает строку SPEC_ITEM в MatchInput для матчера.

    Использует уже сохранённые нормализованные поля, если они есть;
    иначе досчитывает на лету через value_normalizer (тот же код,
    что используется в импортёрах — гарантирует одинаковую логику
    нормализации на обеих сторонах поиска).
    """
    article_norm = spec_item.article_normalized or normalize_article(spec_item.article_raw)
    name_norm = spec_item.name_normalized or normalize_name(spec_item.name_raw)
    unit_norm = spec_item.unit_normalized or (
        spec_item.unit_raw.lower().strip() if spec_item.unit_raw else None
    )
    manufacturer_norm = (
        spec_item.manufacturer_raw.lower().strip() if spec_item.manufacturer_raw else None
    )

    return MatchInput(
        line_number=spec_item.line_number,
        name=spec_item.name_raw,
        name_normalized=name_norm,
        article=spec_item.article_raw,
        article_normalized=article_norm,
        manufacturer=spec_item.manufacturer_raw,
        manufacturer_normalized=manufacturer_norm,
        unit=spec_item.unit_raw,
        unit_normalized=unit_norm,
    )
