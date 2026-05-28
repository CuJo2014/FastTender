"""Все ORM-модели. Импортируются здесь, чтобы Alembic видел метаданные."""

from fasttender.models.base import Base
from fasttender.models.data_source import DataSource
from fasttender.models.enums import (
    DataSourceStatus,
    DataSourceType,
    MatchType,
    SpecificationStatus,
    VerificationDecision,
)
from fasttender.models.item import Item
from fasttender.models.match_candidate import MatchCandidate
from fasttender.models.spec_item import SpecItem
from fasttender.models.specification import Specification
from fasttender.models.supplier import Supplier
from fasttender.models.verification import Verification

__all__ = [
    "Base",
    "DataSource",
    "DataSourceStatus",
    "DataSourceType",
    "Item",
    "MatchCandidate",
    "MatchType",
    "SpecItem",
    "Specification",
    "SpecificationStatus",
    "Supplier",
    "Verification",
    "VerificationDecision",
]
