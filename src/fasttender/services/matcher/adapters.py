"""ORM-аdapters для матчера.

Здесь — единственное место, где `MatchInput` встречается с ORM-моделями.
Это исключает циклические импорты в `types.py`.
"""

from fasttender.models import SpecItem
from fasttender.services.matcher.types import MatchInput
from fasttender.services.parser.value_normalizer import (
    denoise_name,
    extract_article_candidates,
    extract_code_tokens,
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

    # Характеристики/параметры подбора (М10х40, DIN933, 220В) — значимый сигнал
    # для лексического поиска. Подмешиваем их в ТЕКСТ ПОИСКА (name_normalized) и
    # в извлечение кодов, но НЕ в отображаемое имя (input.name остаётся чистым).
    # Тот же приём, что в eval_gold.build_match_input — обе стороны согласованы.
    search_text = spec_item.name_raw
    if spec_item.attributes_raw:
        search_text = f"{spec_item.name_raw} {spec_item.attributes_raw}"
    name_norm = normalize_name(search_text)

    # Денойз-запрос для лексического поиска (вариант A): отрезаем «канцелярский
    # хвост» наименования (комплектация/ГОСТ/упаковка…), который размывает
    # скоринг и топит верные позиции. Характеристики — структурированные
    # параметры подбора, их оставляем целиком. Когда хвоста нет, denoise_name
    # вернёт исходный текст → lexical_query совпадёт с name_norm.
    denoised = denoise_name(spec_item.name_raw)
    if spec_item.attributes_raw:
        denoised = f"{denoised} {spec_item.attributes_raw}" if denoised else (
            spec_item.attributes_raw
        )
    lexical_query = normalize_name(denoised)

    unit_norm = spec_item.unit_normalized or (
        spec_item.unit_raw.lower().strip() if spec_item.unit_raw else None
    )
    manufacturer_norm = (
        spec_item.manufacturer_raw.lower().strip() if spec_item.manufacturer_raw else None
    )

    # Если явного артикула нет — пробуем вытащить код/модель из наименования +
    # характеристик (point 2). При наличии явного артикула это не нужно.
    article_candidates = (
        () if article_norm else tuple(extract_article_candidates(search_text))
    )

    # Длинные цифровые серии для поиска кода в наименовании каталога (задача 3).
    # Извлекаем всегда — модель может быть зашита в имя независимо от наличия
    # отдельного артикула.
    code_tokens = tuple(extract_code_tokens(search_text))

    return MatchInput(
        line_number=spec_item.line_number,
        name=spec_item.name_raw,
        name_normalized=name_norm,
        lexical_query=lexical_query,
        article=spec_item.article_raw,
        article_normalized=article_norm,
        article_candidates=article_candidates,
        code_tokens=code_tokens,
        manufacturer=spec_item.manufacturer_raw,
        manufacturer_normalized=manufacturer_norm,
        unit=spec_item.unit_raw,
        unit_normalized=unit_norm,
    )
