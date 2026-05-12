import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_notifications_list_unauthorized(async_client: AsyncClient):
    """
    Test that listing notifications requires authentication.
    """
    response = await async_client.get("/api/v1/notifications/")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_push_subscription_unauthorized(async_client: AsyncClient):
    """
    Test that registering a push subscription requires authentication.
    """
    response = await async_client.post(
        "/api/v1/notifications/push-subscription",
        json={
            "endpoint": "https://example.com",
            "p256dh": "p256dh",
            "auth": "auth"
        }
    )
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_mark_as_read_unauthorized(async_client: AsyncClient):
    """
    Test that marking a notification as read requires authentication.
    """
    response = await async_client.patch("/api/v1/notifications/1/read")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_notifications_list_authorized(authenticated_async_client: AsyncClient):
    """
    Test that authenticated user can list notifications.
    """
    response = await authenticated_async_client.get("/api/v1/notifications/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

@pytest.mark.asyncio
async def test_push_subscription_authorized(authenticated_async_client: AsyncClient):
    """
    Test that authenticated user can register push subscription.
    """
    response = await authenticated_async_client.post(
        "/api/v1/notifications/push-subscription",
        json={
            "endpoint": "https://example.com/push/123",
            "p256dh": "p256dh_test",
            "auth": "auth_test"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["endpoint"] == "https://example.com/push/123"
    assert "id" in data
