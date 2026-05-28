"""Доменные типы импорта (каталог компании и прайсы поставщиков)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ImportMode(StrEnum):
    """Режим импорта (Приложение C.4)."""

    REPLACE = "replace"
    """Полная замена: все позиции источника деактивируются перед загрузкой новых.

    Используется при штатном обновлении: каталог или прайс выгружается целиком,
    после импорта в источнике лежит только то, что было в файле.
    """

    MERGE = "merge"
    """Слияние: позиции с совпадающим артикулом обновляются, новые добавляются,
    отсутствующие в файле остаются нетронутыми.

    Полезно для инкрементальных дозагрузок.
    """


class RowError(BaseModel):
    """Одна строка, не попавшая в импорт (валидация не прошла)."""

    line_number: int
    reason: str
    raw: dict[str, str | None] = Field(default_factory=dict)


class DuplicateArticle(BaseModel):
    """Дубликат артикула внутри файла — обработан как мягкое предупреждение."""

    article: str
    first_line: int
    duplicate_lines: list[int]


class ImportReport(BaseModel):
    """Результат импорта (Приложение C.4 — /jobs/{id})."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source_id: str
    source_name: str
    mode: ImportMode

    rows_total: int = 0
    """Общее число строк после успешного парсинга (без шапки)."""

    rows_imported: int = 0
    """Сколько новых строк добавлено в Item."""

    rows_updated: int = 0
    """Сколько существующих строк обновлено (только для merge)."""

    rows_deactivated: int = 0
    """Сколько строк помечено is_active=false (только для replace)."""

    rows_skipped: int = 0
    """Сколько строк пропущено из-за валидации."""

    errors: list[RowError] = Field(default_factory=list)
    duplicates: list[DuplicateArticle] = Field(default_factory=list)


class ImportError(Exception):
    """Не удалось выполнить импорт (формат, доступ, нарушение инварианта)."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}
