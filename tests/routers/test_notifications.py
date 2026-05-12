import pytest
from httpx import AsyncClient

from app.models.notification import NotificationType


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

@pytest.mark.asyncio
async def test_notifications_filtering(authenticated_async_client: AsyncClient, db, confirmed_user):
    """
    Test filtering notifications by is_read status.
    """
    user_id = confirmed_user["id"]
    from app.crud.notification import create_notification
    from app.schemas.notification import NotificationCreate

    # Create unread
    await create_notification(db, NotificationCreate(
        user_id=user_id, title="Unread", message="...", type=NotificationType.REMINDER_DUE
    ))
    # Create read (manually set is_read since NotificationCreate doesn't have it)
    from app.models.notification import Notification
    read_noti = Notification(
        user_id=user_id, title="Read", message="...", type=NotificationType.REMINDER_DUE, is_read=True
    )
    db.add(read_noti)
    await db.commit()

    # Filter unread
    response = await authenticated_async_client.get("/api/v1/notifications/?is_read=false")
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Unread"

    # Filter read
    response = await authenticated_async_client.get("/api/v1/notifications/?is_read=true")
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Read"

@pytest.mark.asyncio
async def test_mark_as_read_success(authenticated_async_client: AsyncClient, db, confirmed_user):
    """
    Test successfully marking a notification as read.
    """
    user_id = confirmed_user["id"]
    from app.crud.notification import create_notification
    from app.schemas.notification import NotificationCreate

    noti = await create_notification(db, NotificationCreate(
        user_id=user_id, title="To Read", message="...", type=NotificationType.REMINDER_DUE
    ))
    await db.commit()

    response = await authenticated_async_client.patch(f"/api/v1/notifications/{noti.id}/read")
    assert response.status_code == 200
    assert response.json()["is_read"] is True

@pytest.mark.asyncio
async def test_mark_as_read_not_found_or_not_owned(authenticated_async_client: AsyncClient, db, confirmed_user):
    """
    Test that marking a non-existent or someone else's notification as read returns 404.
    """
    # 404 for non-existent
    response = await authenticated_async_client.patch("/api/v1/notifications/9999/read")
    assert response.status_code == 404

    # Create notification for ANOTHER user
    from app.crud.notification import create_notification
    from app.models.user import User
    from app.schemas.notification import NotificationCreate

    other_user = User(username="other", email="other@example.com", password="...")
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)

    noti = await create_notification(db, NotificationCreate(
        user_id=other_user.id, title="Other Noti", message="...", type=NotificationType.REMINDER_DUE
    ))
    await db.commit()

    # Try to mark someone else's as read
    response = await authenticated_async_client.patch(f"/api/v1/notifications/{noti.id}/read")
    assert response.status_code == 404
