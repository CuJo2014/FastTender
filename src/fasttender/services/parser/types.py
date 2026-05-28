"""Доменные типы парсера спецификаций.

Парсер ничего не знает про БД и ORM — он возвращает чистые dataclass-структуры,
которые конвертируются в SpecItem на уровне выше (Celery-задача parse_specification).
Это позволяет переиспользовать парсер и для импорта каталога/прайсов.

Состав полей — раздел 4.1.3 архитектурного документа.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SpecField(StrEnum):
    """Логические поля строки спецификации (раздел 4.1.3)."""

    NAME = "name"
    ARTICLE = "article"
    MANUFACTURER = "manufacturer"
    QUANTITY = "quantity"
    UNIT = "unit"
    PRICE = "price"
    CURRENCY = "currency"
    DELIVERY_TERM = "delivery_term"
    NOTES = "notes"


class ColumnMapping(BaseModel):
    """Маппинг «логическое поле → индекс колонки (0-based) в исходном файле».

    Сохраняется в DataSource.config или Specification.meta для повторного применения
    к файлам того же клиента/поставщика (раздел 10.2).
    """

    model_config = ConfigDict(frozen=False)

    columns: dict[SpecField, int] = Field(default_factory=dict)

    def get(self, field: SpecField) -> int | None:
        return self.columns.get(field)

    def has(self, field: SpecField) -> bool:
        return field in self.columns

    @property
    def is_usable(self) -> bool:
        """Минимум для парсинга — есть колонка наименования."""
        return SpecField.NAME in self.columns


class ParsedItem(BaseModel):
    """Одна строка спецификации после парсинга (но до доменной нормализации).

    Все поля кроме line_number и raw_row — Optional, так как реальные файлы
    редко заполнены целиком (раздел 4.1.3: «устойчиво работать при заполненности 30%+»).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    line_number: int = Field(..., ge=1, description="Порядковый номер строки в исходнике (1-based)")
    name: str
    article: str | None = None
    manufacturer: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    delivery_term: str | None = None
    notes: str | None = None

    # Оригинал строки целиком — для аудита (раздел 4.2)
    raw_row: dict[str, Any] = Field(default_factory=dict)


class ParseWarning(BaseModel):
    """Не-критичное предупреждение парсинга.

    Например, не удалось распознать число в колонке цены — строка всё равно
    попадает в результат, но менеджер увидит warning в UI.
    """

    line_number: int | None = None
    field: SpecField | None = None
    message: str
    raw_value: str | None = None


class ParseResult(BaseModel):
    """Результат разбора одного файла."""

    items: list[ParsedItem]
    warnings: list[ParseWarning] = Field(default_factory=list)

    # Метаданные о структуре исходника — нужны для UI и для сохранения шаблона
    sheet_name: str | None = None
    header_row: int | None = Field(
        default=None, description="0-based индекс строки шапки в исходнике"
    )
    column_mapping: ColumnMapping = Field(default_factory=ColumnMapping)
    encoding: str | None = None
    delimiter: str | None = None

    @property
    def items_count(self) -> int:
        return len(self.items)

    @property
    def warnings_count(self) -> int:
        return len(self.warnings)


class ParseError(Exception):
    """Парсер не смог обработать файл (формат, кодировка, нет шапки)."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}
