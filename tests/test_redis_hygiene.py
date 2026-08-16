"""Tests for Redis connection hygiene (incident: "max number of clients reached").

Redis Cloud free tier caps concurrent clients (~30). Two unbounded pools
(slowapi's limiter storage + the shared app client) could blow past the cap
under a request storm. The limiter now defaults to in-memory storage and the
app client is hard-capped.
"""

from typing import Any

import pytest

from app import security
from app.limiter import REDIS_LIMITER_POOL_MAX_CONNECTIONS, create_limiter, redact_url


def test_redact_url_strips_credentials() -> None:
    url = "redis://default:supersecret@redis.example.com:14437/0"
    redacted = redact_url(url)
    assert "supersecret" not in redacted
    assert "***" in redacted
    assert "redis.example.com:14437" in redacted


def test_redact_url_passthrough_without_credentials() -> None:
    assert redact_url("redis://localhost:6379/0") == "redis://localhost:6379/0"


def test_limiter_defaults_to_memory_storage(monkeypatch: Any) -> None:
    """Single-instance prod must not open a Redis pool for rate limiting."""
    from limits.storage import MemoryStorage

    monkeypatch.setattr("app.limiter.config.ENV_STATE", "prod")
    monkeypatch.setattr("app.limiter.config.RATE_LIMIT_STORAGE", "memory")

    limiter = create_limiter()
    assert isinstance(limiter._storage, MemoryStorage)


def test_limiter_redis_storage_uses_bounded_pool(monkeypatch: Any) -> None:
    """Opt-in Redis storage must cap its pool under the Redis Cloud client cap."""
    from limits.storage import RedisStorage

    monkeypatch.setattr("app.limiter.config.ENV_STATE", "prod")
    monkeypatch.setattr("app.limiter.config.RATE_LIMIT_STORAGE", "redis")
    monkeypatch.setattr("app.limiter.config.REDIS_URL", "redis://localhost:6379/0")

    limiter = create_limiter()
    assert isinstance(limiter._storage, RedisStorage)
    pool = limiter._storage.storage.connection_pool
    assert pool.max_connections == REDIS_LIMITER_POOL_MAX_CONNECTIONS
    assert pool.max_connections < 30  # Redis Cloud free tier cap


def test_app_redis_client_uses_bounded_pool(mocker: Any) -> None:
    """The shared app client must never grow past its hard cap."""
    mock_from_url = mocker.patch("redis.asyncio.from_url", return_value=mocker.AsyncMock())
    mocker.patch("app.security.REDIS_URL", "redis://localhost:6379/0")

    security._redis_client = None
    try:
        security._build_redis_client()
    finally:
        security._redis_client = None

    kwargs = mock_from_url.call_args.kwargs
    assert kwargs["max_connections"] == security.REDIS_POOL_MAX_CONNECTIONS
    assert kwargs["max_connections"] < 30
    assert kwargs["health_check_interval"] == security.REDIS_POOL_HEALTH_CHECK_INTERVAL


@pytest.mark.anyio
async def test_blacklist_check_fails_open_on_redis_error(mocker: Any) -> None:
    """A Redis outage must not 401 every request (mass-logout storm guard)."""
    mock_redis = mocker.MagicMock()
    mock_redis.exists = mocker.AsyncMock(side_effect=RuntimeError("redis boom"))
    mocker.patch("app.security.get_redis_client", return_value=mock_redis)

    assert await security.is_token_blacklisted("some-token") is False


@pytest.mark.anyio
async def test_blacklist_check_fails_open_on_loop_reset_failure(mocker: Any) -> None:
    """Even the event-loop re-init retry path degrades open, never raises."""
    mock_redis = mocker.MagicMock()
    mock_redis.exists = mocker.AsyncMock(side_effect=RuntimeError("Event loop is closed"))
    mocker.patch("app.security.get_redis_client", return_value=mock_redis)

    assert await security.is_token_blacklisted("some-token") is False
