"""Unit tests for the pure LWW merge engine (app/sync/lww.py)."""

from datetime import datetime, timezone

import pytest

from app.sync.lww import decide_apply, merge_payload

UTC = timezone.utc


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 13, hour, minute, 0, tzinfo=UTC)


def test_apply_when_client_newer():
    assert decide_apply(_ts(10), _ts(9)) is True


def test_reject_when_server_newer():
    assert decide_apply(_ts(9), _ts(10)) is False


def test_equal_timestamp_tiebreak():
    # Deterministic tiebreak: server wins (documented in lww.py) — the change
    # is reported as a conflict so a client replay can never double-apply.
    assert decide_apply(_ts(10), _ts(10)) is False


def test_merge_payload_whitelist():
    whitelist = {"title", "completed"}
    payload = {
        "title": "x",
        "completed": True,
        "user_id": 999,
        "id": 5,
        "updated_at": "2026-01-01T00:00:00Z",
        "unknown_key": "dropped",
    }
    merged = merge_payload(payload, whitelist)
    assert merged == {"title": "x", "completed": True}
    # non-whitelisted keys dropped silently; unknown keys never raise
    assert "user_id" not in merged
    assert "unknown_key" not in merged


def test_delete_wins_when_newer():
    # Delete shares the same LWW comparison as update (router-level behavior);
    # the decision itself is: newer client timestamp wins.
    assert decide_apply(_ts(10), _ts(9)) is True


def test_delete_stale_returns_conflict():
    assert decide_apply(_ts(9), _ts(10)) is False


def test_naive_client_timestamp_raises():
    with pytest.raises(ValueError, match="timezone-aware"):
        decide_apply(datetime(2026, 8, 13, 10, 0, 0), _ts(9))
