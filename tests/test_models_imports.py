"""Проверяем, что все модели регистрируются в metadata (Alembic-friendly)."""

from fasttender.models import Base


def test_all_tables_registered() -> None:
    expected = {
        "supplier",
        "data_source",
        "item",
        "specification",
        "spec_item",
        "match_candidate",
        "verification",
    }
    actual = set(Base.metadata.tables.keys())
    assert expected.issubset(actual), f"Missing tables: {expected - actual}"
