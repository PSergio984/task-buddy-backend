"""Tests for logout token blacklisting."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.security import is_token_blacklisted


@pytest.fixture(autouse=True)
def mock_redis_security(mocker: Any):
    """Override the global autouse fixture with a stateful mock Redis client."""
    blacklist = set()

    async def mock_setex(key, expires, value):
        blacklist.add(key)
        return True

    async def mock_exists(key):
        return 1 if key in blacklist else 0

    mock_redis = mocker.MagicMock()
    mock_redis.setex = mocker.AsyncMock(side_effect=mock_setex)
    mock_redis.exists = mocker.AsyncMock(side_effect=mock_exists)

    # Patch get_redis_client in app.security so the real blacklist_token/is_token_blacklisted use it
    mocker.patch("app.security.get_redis_client", return_value=mock_redis)



@pytest.mark.anyio
async def test_logout_blacklists_token(
    async_client: AsyncClient, confirmed_user: dict[str, Any]
) -> None:
    """Verify logout blacklists the token and subsequent requests are rejected."""
    # 1. Login to get a token
    login_response = await async_client.post(
        "/api/v1/users/token",
        data={
            "username": confirmed_user["email"],
            "password": confirmed_user["password"],
        },
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Verify token works initially
    me_response = await async_client.get("/api/v1/users/me", headers=headers)
    assert me_response.status_code == 200
    assert me_response.json()["email"] == confirmed_user["email"]

    # 3. Verify token is NOT blacklisted yet
    assert await is_token_blacklisted(token) is False

    # 4. Logout (this should trigger blacklisting in Redis)
    logout_response = await async_client.post("/api/v1/users/logout", headers=headers)
    assert logout_response.status_code == 200
    assert "Successfully logged out" in logout_response.json()["detail"]

    # 5. Verify token IS now blacklisted
    assert await is_token_blacklisted(token) is True

    # 6. Verify token is rejected by the API
    me_response_post_logout = await async_client.get("/api/v1/users/me", headers=headers)
    assert me_response_post_logout.status_code == 401
    assert "blacklisted" in me_response_post_logout.json()["detail"].lower()
