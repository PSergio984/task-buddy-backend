import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_idempotency_concurrent_same_key(authenticated_async_client: AsyncClient, mocker):
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
        return_exceptions=True
    )

    status_codes = [r.status_code for r in responses if not isinstance(r, BaseException)]

    # One should be 201 (Created), the other 409 (Conflict)
    assert 201 in status_codes
    assert 409 in status_codes


@pytest.mark.anyio
async def test_idempotency_server_error_clears_lock(authenticated_async_client: AsyncClient, mocker):
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
    with patch("app.api.routers.project.project_crud.create_project", side_effect=Exception("Database error")):
        # AsyncClient might propagate the exception if not caught by an exception handler middleware
        # that's outside our idempotency middleware.
        try:
            await authenticated_async_client.post("/api/v1/projects/", json={"name": "Fail"}, headers=headers)
        except Exception:
            pass

        # Ensure delete was called to clear the lock in the middleware's 'except' block
        assert mock_redis.delete.called


@pytest.mark.anyio
async def test_idempotency_redis_unavailable_fails_open(authenticated_async_client: AsyncClient, mocker):
    """
    Test that if Redis is down, the request still proceeds (fail open).
    """
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=None)

    idempotency_key = str(uuid.uuid4())
    headers = {"X-Idempotency-Key": idempotency_key}

    response = await authenticated_async_client.post("/api/v1/projects/", json={"name": "Open"}, headers=headers)
    assert response.status_code == 201
