import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.notification import (
    create_notification,
    create_or_update_push_subscription,
    delete_push_subscription,
    get_notifications,
    mark_notification_as_read,
)
from app.models.notification import NotificationType, PushSubscription
from app.schemas.notification import NotificationCreate, PushSubscriptionCreate


@pytest.mark.anyio
async def test_create_and_get_notification(db: AsyncSession, confirmed_user: dict):
    user_id = confirmed_user["id"]
    noti_in = NotificationCreate(
        user_id=user_id,
        title="Test Noti",
        message="Test Message",
        type=NotificationType.SYSTEM,
    )

    noti = await create_notification(db, noti_in)
    await db.commit()

    notifications = await get_notifications(db, user_id=user_id)
    assert len(notifications) == 1
    assert notifications[0].title == "Test Noti"
    assert notifications[0].is_read is False


@pytest.mark.anyio
async def test_mark_as_read(db: AsyncSession, confirmed_user: dict):
    user_id = confirmed_user["id"]
    noti_in = NotificationCreate(
        user_id=user_id, title="Test Noti", message="Test Message", type=NotificationType.SYSTEM
    )
    noti = await create_notification(db, noti_in)
    await db.commit()

    updated_noti = await mark_notification_as_read(db, noti.id, user_id)
    await db.commit()

    assert updated_noti is not None
    assert updated_noti.is_read is True

    notifications = await get_notifications(db, user_id=user_id, is_read=True)
    assert len(notifications) == 1


@pytest.mark.anyio
async def test_push_subscription_upsert(db: AsyncSession, confirmed_user: dict):
    user_id = confirmed_user["id"]
    sub_in = PushSubscriptionCreate(
        endpoint="https://example.com/endpoint", p256dh="p256dh", auth="auth"
    )

    sub = await create_or_update_push_subscription(db, user_id, sub_in)
    await db.commit()

    assert sub.endpoint == "https://example.com/endpoint"

    # Update
    sub_in_updated = PushSubscriptionCreate(
        endpoint="https://example.com/endpoint", p256dh="new_p256dh", auth="new_auth"
    )
    sub_updated = await create_or_update_push_subscription(db, user_id, sub_in_updated)
    await db.commit()

    assert sub_updated.id == sub.id
    assert sub_updated.p256dh == "new_p256dh"


@pytest.mark.anyio
async def test_delete_push_subscription(db: AsyncSession, confirmed_user: dict):
    user_id = confirmed_user["id"]
    endpoint = "https://example.com/endpoint"
    sub_in = PushSubscriptionCreate(endpoint=endpoint, p256dh="p256dh", auth="auth")
    await create_or_update_push_subscription(db, user_id, sub_in)
    await db.commit()

    await delete_push_subscription(db, endpoint)
    await db.commit()

    # Try to find it
    result = await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    assert result.scalar_one_or_none() is None
