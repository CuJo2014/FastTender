"""Все ORM-модели. Импортируются здесь, чтобы Alembic видел метаданные."""

from fasttender.models.base import Base
from fasttender.models.client import Client
from fasttender.models.data_source import DataSource
from fasttender.models.enums import (
    DataSourceStatus,
    DataSourceType,
    GoldLabelStatus,
    MatchType,
    SpecificationStatus,
    VerificationDecision,
)
from fasttender.models.gold_row import GoldRow
from fasttender.models.item import Item
from fasttender.models.match_candidate import MatchCandidate
from fasttender.models.spec_item import SpecItem
from fasttender.models.specification import Specification
from fasttender.models.supplier import Supplier
from fasttender.models.trading_platform import TradingPlatform
from fasttender.models.verification import Verification

__all__ = [
    "Base",
    "Client",
    "DataSource",
    "DataSourceStatus",
    "DataSourceType",
    "GoldLabelStatus",
    "GoldRow",
    "Item",
    "MatchCandidate",
    "MatchType",
    "SpecItem",
    "Specification",
    "SpecificationStatus",
    "Supplier",
    "TradingPlatform",
    "Verification",
    "VerificationDecision",
]
