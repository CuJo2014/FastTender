"""Конфигурируемые трансформации ParsedItem на уровне поставщика.

Реальные прайсы разных поставщиков различаются по «упаковке» данных:
бренд внутри Наименования через `// Sparta`, цены с/без НДС, пустые
колонки единиц измерения и валюты, и т.д. Писать парсер под каждый
формат — путь в ад: для одного работает, для другого нет.

Вместо этого — небольшой набор флагов в `Supplier.meta["transformations"]`,
выставляемых через UI один раз при заведении поставщика. Применяются
к каждой ParsedItem после парсинга, до dedupe/upsert.

Поддерживаемые трансформации (см. SupplierTransformations):
  - brand_regex: извлечь бренд из Наименования (если manufacturer пустой),
                 очистить имя от хвоста.
  - vat_included + vat_rate: убрать НДС из цены (price /= 1 + rate/100).
  - default_unit, default_currency: подставить если пусто.

В будущем (Phase 2) добавится визуальный editor с preview эффекта.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fasttender.services.parser import ParsedItem


class SupplierTransformations(BaseModel):
    """Конфиг трансформаций. Хранится в Supplier.meta["transformations"]."""

    model_config = ConfigDict(extra="ignore")

    brand_regex: str | None = Field(
        None,
        description=(
            "Regex с двумя группами: (clean_name, brand). Применяется к "
            "Наименованию, если manufacturer пустой. Пример: "
            r"^(.+?)\s*//\s*(.+?)\s*$ — извлекает «Sparta» из «Болт // Sparta»."
        ),
    )
    vat_included: bool = Field(False, description="Цена в файле уже включает НДС → убрать.")
    vat_rate: int = Field(20, ge=0, le=100, description="Ставка НДС в процентах.")
    default_unit: str | None = Field(
        None, description="Подставить в Ед.изм. если пусто (например, «шт»)."
    )
    default_currency: str | None = Field(
        None, description="Подставить в Валюту если пусто (например, «RUB»)."
    )
    manufacturer: str | None = Field(
        None,
        max_length=255,
        description=(
            "Принудительный производитель для ВСЕХ позиций прайса (перетирает "
            "то что было определено из файла). Используется для прайсов "
            "одного бренда: MIL → «Milwaukee», MKT → «Makita»."
        ),
    )

    @field_validator("brand_regex")
    @classmethod
    def _validate_brand_regex(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            pattern = re.compile(v)
        except re.error as exc:
            raise ValueError(f"Невалидный регэксп: {exc}") from exc
        if pattern.groups != 2:
            raise ValueError(
                f"brand_regex должен содержать ровно 2 группы (clean_name, brand), найдено {pattern.groups}"
            )
        return v

    @classmethod
    def from_meta(cls, meta: dict[str, Any] | None) -> SupplierTransformations:
        """Достаёт конфиг из supplier.meta. Пустой meta → дефолтный (все no-op)."""
        if not meta:
            return cls()
        raw = meta.get("transformations")
        if not raw or not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            # Сломанный конфиг не должен ронять импорт — используем дефолт
            return cls()

    @property
    def is_noop(self) -> bool:
        """True если конфиг ничего не делает — можно пропустить применение."""
        return (
            self.brand_regex is None
            and not self.vat_included
            and self.default_unit is None
            and self.default_currency is None
            and self.manufacturer is None
        )


def apply_transformations(
    items: list[ParsedItem], config: SupplierTransformations
) -> list[ParsedItem]:
    """Применяет трансформации ко всем строкам прайса. Возвращает новый список.

    ParsedItem иммутабельный (Pydantic v2 immutable by default), поэтому
    создаём через model_copy(update=...) — это и быстрее, чем заново строить.
    """
    if config.is_noop:
        return items

    brand_pattern = re.compile(config.brand_regex) if config.brand_regex else None
    vat_divisor = Decimal(100 + config.vat_rate) / Decimal(100) if config.vat_included else None

    out: list[ParsedItem] = []
    for item in items:
        updates: dict[str, Any] = {}

        # 1. brand_regex — только если manufacturer пустой, иначе доверяем парсеру
        if brand_pattern is not None and not item.manufacturer:
            m = brand_pattern.match(item.name)
            if m:
                clean_name = m.group(1).strip()
                brand = m.group(2).strip()
                if clean_name and brand:
                    updates["name"] = clean_name
                    updates["manufacturer"] = brand

        # 2. НДС
        if vat_divisor is not None and item.price is not None:
            updates["price"] = (item.price / vat_divisor).quantize(Decimal("0.0001"))

        # 3. Дефолты для пустых полей
        if config.default_unit and not item.unit:
            updates["unit"] = config.default_unit
        if config.default_currency and not item.currency:
            updates["currency"] = config.default_currency

        # 4. Принудительный производитель — перетирает то что было определено
        # из файла. Для прайсов одного бренда (MIL, MKT).
        if config.manufacturer:
            updates["manufacturer"] = config.manufacturer

        out.append(item.model_copy(update=updates) if updates else item)
    return out
