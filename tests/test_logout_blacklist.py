import pytest
from httpx import AsyncClient

from app.security import is_token_blacklisted


@pytest.fixture(autouse=True)
def disable_redis_mock(mocker):
    """Disable the global mock from conftest.py to test real Redis integration."""
    # We don't call mocker.patch here, so the real functions are used.
    # But since conftest.py's mock_redis_security is autouse=True,
    # we must override it specifically for this module.
    pass

@pytest.fixture(autouse=True)
def mock_redis_security():
    """Override the global autouse fixture from conftest.py."""
    # By doing nothing, we allow the real implementation to be used.
    pass

@pytest.mark.asyncio
async def test_logout_blacklists_token(async_client: AsyncClient, confirmed_user: dict):
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
