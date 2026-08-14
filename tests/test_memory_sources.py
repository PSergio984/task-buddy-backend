"""Unit tests for the history Source and row-build helpers (plan 08-01)."""

from app.knowledge.history import build_history_content, compute_duration_minutes
from app.knowledge.sources import source_registry
from app.knowledge.sources.history import HistorySource
from app.models.knowledge import SourceType


def test_history_source_extract_returns_content() -> None:
    assert HistorySource(content="x").extract() == "x"


def test_history_source_registered_in_registry() -> None:
    source = source_registry.create(SourceType.HISTORY, {"content": "abc"})
    assert source.extract() == "abc"


def test_history_duration_minutes_math() -> None:
    from datetime import datetime, timedelta

    created = datetime(2026, 1, 1, 10, 0)
    updated = created + timedelta(minutes=90)
    assert compute_duration_minutes(created, updated) == 90.0
    assert compute_duration_minutes(created, created) == 0.0
    # Negative (updated < created, clock skew) clamps to 0.0.
    assert compute_duration_minutes(updated, created) == 0.0


def test_history_content_joins_title_description() -> None:
    assert build_history_content("T", "D") == "T\nD"
    assert build_history_content("T", None) == "T"
    assert build_history_content("T", "") == "T"
