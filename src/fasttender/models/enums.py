"""Перечисления, общие для нескольких моделей."""

from enum import StrEnum


class DataSourceType(StrEnum):
    """Тип источника данных (раздел 7.1, 8.2).

    Каталог и прайсы хранятся в единой таблице ITEM — различаются только этим полем.
    web_scraper заложен на Фазу 2 (см. раздел 11), но enum включает его уже сейчас.
    """

    COMPANY_CATALOG = "company_catalog"
    SUPPLIER_PRICELIST = "supplier_pricelist"
    WEB_SCRAPER = "web_scraper"


class DataSourceStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class SpecificationStatus(StrEnum):
    """Статусы жизненного цикла спецификации (раздел 7.4)."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSE_FAILED = "parse_failed"
    PARSED = "parsed"
    MATCHING = "matching"
    MATCH_FAILED = "match_failed"
    MATCHED = "matched"  # deprecated: оставлен для совместимости. Pipeline → REVIEWING
    REVIEWING = "reviewing"
    VERIFIED = "verified"
    EXPORTED = "exported"
    CANCELLED = "cancelled"  # менеджер отказался обеспечивать поставку


class MatchType(StrEnum):
    """Тип совпадения для MatchCandidate (раздел 9.1)."""

    EXACT_ARTICLE = "exact_article"
    FUZZY_ARTICLE = "fuzzy_article"
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class VerificationDecision(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"
    NEW_ITEM_REQUESTED = "new_item_requested"


class GoldLabelStatus(StrEnum):
    """Статус разметки строки золотого датасета (раздел 15.4, 16.3).

    Значения совпадают со строками, которые читает `eval_gold.py`
    (STATUS_FOUND / STATUS_ANALOG / STATUS_NOT_FOUND / STATUS_UNSURE), чтобы
    экспорт в Excel-шаблон не требовал преобразования.
    """

    FOUND = "найдено"
    ANALOG = "аналог"
    NOT_FOUND = "не найдено"
    UNSURE = "сомнительно"
