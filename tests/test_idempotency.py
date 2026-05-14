import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_idempotency_middleware_caching(async_client: AsyncClient, logged_in_token: str, mocker):
    # Mock Redis client
    mock_redis = AsyncMock()
    # Initial state: key not in cache
    mock_redis.get.return_value = None
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=mock_redis)
    mocker.patch("app.security.get_redis_client", return_value=mock_redis)

    # First request
    idempotency_key = str(uuid.uuid4())
    headers = {
        "X-Idempotency-Key": idempotency_key,
        "Authorization": f"Bearer {logged_in_token}"
    }
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
async def test_idempotency_invalid_format(async_client: AsyncClient, logged_in_token: str):
    headers = {
        "X-Idempotency-Key": "not-a-uuid",
        "Authorization": f"Bearer {logged_in_token}"
    }
    response = await async_client.post("/api/v1/tasks/", json={}, headers=headers)
    assert response.status_code == 400
    assert "Invalid X-Idempotency-Key format" in response.text
