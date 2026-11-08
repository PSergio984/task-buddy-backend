"""Tests for idempotency edge cases: concurrency, failures, and Redis outages."""

import asyncio
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_idempotency_concurrent_same_key(
    authenticated_async_client: AsyncClient, mocker: Any
) -> None:
    """
    Test that concurrent requests with the same idempotency key result in only one success
    and others getting a 409 Conflict.
    """
    idempotency_key = str(uuid.uuid4())
    headers = {"X-Idempotency-Key": idempotency_key}

    mock_redis = AsyncMock()
    # Mock set(nx=True) to succeed only once for the same key
    lock_acquired = [False]

    async def mock_set(key, value, ex=None, nx=False):
        if nx and value == json.dumps("IN_PROGRESS"):
            if not lock_acquired[0]:
                lock_acquired[0] = True
                return True
            return False
        return True

    mock_redis.set.side_effect = mock_set
    mock_redis.get.return_value = None

    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=mock_redis)
    mocker.patch("app.security.get_redis_client", return_value=mock_redis)

    # Fire two concurrent requests
    responses = await asyncio.gather(
        authenticated_async_client.post("/api/v1/projects/", json={"name": "P1"}, headers=headers),
        authenticated_async_client.post("/api/v1/projects/", json={"name": "P1"}, headers=headers),
        return_exceptions=True,
    )

    status_codes = [r.status_code for r in responses if not isinstance(r, BaseException)]

    # One should be 201 (Created), the other 409 (Conflict)
    assert 201 in status_codes
    assert 409 in status_codes


@pytest.mark.anyio
async def test_idempotency_server_error_clears_lock(
    authenticated_async_client: AsyncClient, mocker: Any
) -> None:
    """
    Test that if a request fails with a 500 error, the idempotency lock is cleared
    so the user can retry.
    """
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.set.return_value = True

    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=mock_redis)

    idempotency_key = str(uuid.uuid4())
    headers = {"X-Idempotency-Key": idempotency_key}

    # Force a 500 error by hitting an endpoint and mocking the service to fail
    with patch(
        "app.api.routers.project.project_crud.create_project",
        side_effect=Exception("Database error"),
    ):
        # AsyncClient might propagate the exception if not caught by an exception handler middleware
        # that's outside our idempotency middleware.
        try:
            await authenticated_async_client.post(
                "/api/v1/projects/", json={"name": "Fail"}, headers=headers
            )
        except Exception:
            pass

        # Ensure delete was called to clear the lock in the middleware's 'except' block
        assert mock_redis.delete.called


@pytest.mark.anyio
async def test_idempotency_redis_unavailable_fails_open(
    authenticated_async_client: AsyncClient, mocker: Any
) -> None:
    """
    Test that if Redis is down, the request still proceeds (fail open).
    """
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=None)

    idempotency_key = str(uuid.uuid4())
    headers = {"X-Idempotency-Key": idempotency_key}

    response = await authenticated_async_client.post(
        "/api/v1/projects/", json={"name": "Open"}, headers=headers
    )
    assert response.status_code == 201


@pytest.mark.anyio
async def test_idempotency_redis_error_fails_open(
    authenticated_async_client: AsyncClient, mocker: Any
) -> None:
    """
    A lazy client whose every call raises (e.g. dead Redis hostname) must
    fail open like the missing-client path — a lock-acquisition error is
    not a held lock, so it can't 409 every keyed POST into a write outage.
    """
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = ConnectionError("Redis is down")
    mock_redis.set.side_effect = ConnectionError("Redis is down")

    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=mock_redis)

    headers = {"X-Idempotency-Key": str(uuid.uuid4())}
    response = await authenticated_async_client.post(
        "/api/v1/projects/", json={"name": "Still works"}, headers=headers
    )
    assert response.status_code == 201
    # The fail-open must come from the errored lock path — if the request
    # bypassed `set` entirely, it silently took the missing-client branch.
    mock_redis.set.assert_awaited()


@pytest.mark.anyio
async def test_idempotency_cache_write_error_returns_response(
    authenticated_async_client: AsyncClient, mocker: Any
) -> None:
    """
    Redis dying after the lock was acquired must not 500 a finished
    request — the handler already ran, so its response returns uncached.
    """
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    async def mock_set(key, value, ex=None, nx=False):
        if nx:
            return True  # lock acquired before Redis died
        raise ConnectionError("Redis died mid-request")

    mock_redis.set.side_effect = mock_set
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=mock_redis)

    headers = {"X-Idempotency-Key": str(uuid.uuid4())}
    response = await authenticated_async_client.post(
        "/api/v1/projects/", json={"name": "Uncached"}, headers=headers
    )
    assert response.status_code == 201


@pytest.mark.anyio
async def test_idempotency_lock_cleanup_error_returns_response(
    authenticated_async_client: AsyncClient, mocker: Any
) -> None:
    """
    Redis dying on lock cleanup must not mask the handler's own response —
    a 422 from validation stays a 422, not a 500 from the delete.
    """
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.set.return_value = True
    mock_redis.delete.side_effect = ConnectionError("Redis died mid-request")

    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=mock_redis)

    headers = {"X-Idempotency-Key": str(uuid.uuid4())}
    response = await authenticated_async_client.post("/api/v1/projects/", json={}, headers=headers)
    assert response.status_code == 422
