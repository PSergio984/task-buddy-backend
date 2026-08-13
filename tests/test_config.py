"""Tests for SECRET_KEY resolution and environment gating."""

import pytest

from app.config import DEV_SECRET_KEY, _resolve_secret_key


def test_dev_unset_uses_dev_key():
    assert _resolve_secret_key(None, "dev") == DEV_SECRET_KEY


def test_dev_real_key_passthrough():
    assert _resolve_secret_key("my-real-secret", "dev") == "my-real-secret"


def test_test_unset_uses_dev_key():
    assert _resolve_secret_key(None, "test") == DEV_SECRET_KEY


def test_prod_real_key_passthrough():
    assert _resolve_secret_key("my-real-secret", "prod") == "my-real-secret"


def test_prod_unset_raises():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _resolve_secret_key(None, "prod")


def test_prod_with_dev_key_raises():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _resolve_secret_key(DEV_SECRET_KEY, "prod")


def test_unknown_env_state_unset_raises():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _resolve_secret_key(None, "staging")


def test_unknown_env_state_with_dev_key_raises():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _resolve_secret_key(DEV_SECRET_KEY, "staging")


def test_knowledge_feedback_rate_limit_matches_spec():
    """RATE_LIMIT_KNOWLEDGE_FEEDBACK is 30/minute in TestConfig AND re-export."""
    from app.config import RATE_LIMIT_KNOWLEDGE_FEEDBACK, TestConfig

    assert TestConfig().RATE_LIMIT_KNOWLEDGE_FEEDBACK == "30/minute"
    assert RATE_LIMIT_KNOWLEDGE_FEEDBACK == "30/minute"
