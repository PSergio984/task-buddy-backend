"""Tests for the idempotency middleware."""

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_idempotency_middleware_caching(
    async_client: AsyncClient, logged_in_token: str, mocker: Any
) -> None:
    """Verify a repeated request with the same idempotency key is served from cache."""
    # Mock Redis client
    mock_redis = AsyncMock()
    # Initial state: key not in cache
    mock_redis.get.return_value = None
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=mock_redis)
    mocker.patch("app.security.get_redis_client", return_value=mock_redis)

    # First request
    idempotency_key = str(uuid.uuid4())
    headers = {"X-Idempotency-Key": idempotency_key, "Authorization": f"Bearer {logged_in_token}"}
    payload = {"title": "Test Task", "description": "Testing idempotency"}

    # Send first request
    response1 = await async_client.post("/api/v1/tasks/", json=payload, headers=headers)

    assert response1.status_code in [200, 201], f"First request failed: {response1.text}"
    assert mock_redis.get.call_count == 1
    # set is called twice: 1 for IN_PROGRESS, 1 for the actual response
    assert mock_redis.set.call_count == 2

    # Get the data that was cached (the last set call)
    cache_data = mock_redis.set.call_args[0][1]

    # Mock Redis to return the cached response for the second request
    mock_redis.get.return_value = cache_data

    # Second request with same key
    response2 = await async_client.post("/api/v1/tasks/", json=payload, headers=headers)

    assert response2.status_code == response1.status_code
    assert response2.json() == response1.json()

    # Ensure it was a cache hit (get was called again)
    assert mock_redis.get.call_count == 2
    # Ensure set was NOT called again for the second request
    assert mock_redis.set.call_count == 2


@pytest.mark.anyio
async def test_idempotency_invalid_format(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify an invalid idempotency key format returns 400."""
    headers = {"X-Idempotency-Key": "not-a-uuid", "Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.post("/api/v1/tasks/", json={}, headers=headers)
    assert response.status_code == 400
    assert "Invalid X-Idempotency-Key format" in response.text


@pytest.mark.anyio
async def test_idempotency_body_mismatch_returns_422(
    async_client: AsyncClient, logged_in_token: str, mocker: Any
) -> None:
    """Same key + same body replays the cached response; same key + different
    body returns 422 — replaying would silently drop the new request."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=mock_redis)
    mocker.patch("app.security.get_redis_client", return_value=mock_redis)

    idempotency_key = str(uuid.uuid4())
    headers = {"X-Idempotency-Key": idempotency_key, "Authorization": f"Bearer {logged_in_token}"}

    response1 = await async_client.post("/api/v1/tasks/", json={"title": "Task A"}, headers=headers)
    assert response1.status_code in [200, 201], f"First request failed: {response1.text}"

    # Serve subsequent reads from what the middleware cached.
    mock_redis.get.return_value = mock_redis.set.call_args[0][1]

    # Same key + same body -> cached replay.
    response2 = await async_client.post("/api/v1/tasks/", json={"title": "Task A"}, headers=headers)
    assert response2.status_code == response1.status_code
    assert response2.json() == response1.json()

    # Same key + different body -> 422, not a stale replay.
    response3 = await async_client.post("/api/v1/tasks/", json={"title": "Task B"}, headers=headers)
    assert response3.status_code == 422


@pytest.mark.anyio
async def test_idempotency_oversize_body_bypasses_cache(
    async_client: AsyncClient, logged_in_token: str, mocker: Any
) -> None:
    """A body past MAX_BODY_BYTES passes through uncached — buffering it to
    hash would be a memory DoS; oversize calls get no dedup protection."""
    mock_redis = AsyncMock()
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=mock_redis)
    mocker.patch("app.security.get_redis_client", return_value=mock_redis)

    headers = {
        "X-Idempotency-Key": str(uuid.uuid4()),
        "Authorization": f"Bearer {logged_in_token}",
    }
    payload = {"title": "Big Task", "description": "x" * 1_100_000}
    first = await async_client.post("/api/v1/tasks/", json=payload, headers=headers)
    second = await async_client.post("/api/v1/tasks/", json=payload, headers=headers)
    assert first.status_code == second.status_code
    # Redis was never consulted — the bypass precedes the cache lookup.
    mock_redis.get.assert_not_called()
    mock_redis.set.assert_not_called()
