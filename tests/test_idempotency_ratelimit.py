import uuid

import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_ratelimit_not_cached_by_idempotency(authenticated_async_client: AsyncClient, mocker):
    # Enable limiter specifically for this test
    app.state.limiter.enabled = True
    # Reset limiter to ensure we start fresh
    app.state.limiter.reset()
    try:
        # Mock the key function that slowapi actually uses
        mocker.patch("slowapi.util.get_remote_address", return_value="1.2.3.4")

        # We need to make sure the rate limit is hit.
        # /api/v1/projects/ has a limit of 10/minute.

        idempotency_key = str(uuid.uuid4())
        headers = {"X-Idempotency-Key": idempotency_key}

        # 1. Hit the limit (10 per minute)
        for _ in range(10):
            response = await authenticated_async_client.post(
                "/api/v1/projects/",
                json={"name": f"Project {uuid.uuid4()}"}
            )
            assert response.status_code != 429

        # 2. 11th request with idempotency key - should be rate limited (429)
        # This request will NOT be cached because of our fix.
        response = await authenticated_async_client.post(
            "/api/v1/projects/",
            json={"name": "Final Project"},
            headers=headers
        )
        assert response.status_code == 429

        # 3. Manually reset the limiter to simulate time passing or limit reset
        # Since we use Redis now in app/limiter.py, reset() might need to clear Redis.
        # But in tests, if Redis is not connected, it might be using in-memory fallback?
        # Let's check app/limiter.py.
        app.state.limiter.reset()

        # 4. Try again with the SAME idempotency key.
        # If the 429 was NOT cached, this should now proceed to the handler.
        # It might return 201 (Created) or 400 (if we didn't reset everything).
        response = await authenticated_async_client.post(
            "/api/v1/projects/",
            json={"name": "Final Project Unique"},
            headers=headers
        )

        # If it was cached, it would be 429. If not cached, it should be 201.
        assert response.status_code == 201

    finally:
        app.state.limiter.reset()
        app.state.limiter.enabled = False
