from datetime import datetime, timedelta, timezone

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
from app.models.notification import Notification, NotificationType, PushSubscription
from app.models.task import Task
from app.schemas.notification import NotificationCreate, PushSubscriptionCreate
from app.tasks import _process_reminders_async


@pytest.mark.asyncio
async def test_create_notification(db: AsyncSession, confirmed_user: dict):
    user_id = confirmed_user["id"]
    notification_in = NotificationCreate(
        user_id=user_id,
        title="Test Title",
        message="Test Message",
        type=NotificationType.REMINDER_DUE
    )
    notification = await create_notification(db, notification_in)
    assert notification.id is not None
    assert notification.title == "Test Title"
    assert notification.user_id == user_id

@pytest.mark.asyncio
async def test_get_notifications(db: AsyncSession, confirmed_user: dict):
    user_id = confirmed_user["id"]
    # Create 3 notifications with different titles
    for i in range(3):
        notification_in = NotificationCreate(
            user_id=user_id,
            title=f"Title {i}",
            message=f"Message {i}",
            type=NotificationType.REMINDER_DUE
        )
        await create_notification(db, notification_in)

    notifications = await get_notifications(db, user_id)
    assert len(notifications) == 3
    # Just check that we have 3, order might be tricky with identical timestamps in SQLite
    titles = [n.title for n in notifications]
    assert "Title 0" in titles
    assert "Title 1" in titles
    assert "Title 2" in titles

@pytest.mark.asyncio
async def test_mark_as_read(db: AsyncSession, confirmed_user: dict):
    user_id = confirmed_user["id"]
    notification_in = NotificationCreate(
        user_id=user_id,
        title="Test Title",
        message="Test Message",
        type=NotificationType.REMINDER_DUE
    )
    notification = await create_notification(db, notification_in)
    assert notification.is_read is False

    updated = await mark_notification_as_read(db, notification.id, user_id)
    assert updated.is_read is True

@pytest.mark.asyncio
async def test_push_subscription_upsert(db: AsyncSession, confirmed_user: dict):
    user_id = confirmed_user["id"]
    sub_in = PushSubscriptionCreate(
        endpoint="https://example.com/1",
        p256dh="p1",
        auth="a1"
    )
    # Create
    sub = await create_or_update_push_subscription(db, user_id, sub_in)
    assert sub.id is not None
    assert sub.p256dh == "p1"

    # Update
    sub_in_updated = PushSubscriptionCreate(
        endpoint="https://example.com/1",
        p256dh="p1-updated",
        auth="a1-updated"
    )
    sub_updated = await create_or_update_push_subscription(db, user_id, sub_in_updated)
    assert sub_updated.id == sub.id
    assert sub_updated.p256dh == "p1-updated"

@pytest.mark.asyncio
async def test_delete_push_subscription(db: AsyncSession, confirmed_user: dict):
    user_id = confirmed_user["id"]
    endpoint = "https://example.com/del"
    sub_in = PushSubscriptionCreate(
        endpoint=endpoint,
        p256dh="p1",
        auth="a1"
    )
    await create_or_update_push_subscription(db, user_id, sub_in)

    # Verify exists
    stmt = select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    res = await db.execute(stmt)
    assert res.scalar_one_or_none() is not None

    await delete_push_subscription(db, endpoint)

    # Verify gone
    res = await db.execute(stmt)
    assert res.scalar_one_or_none() is None

@pytest.mark.asyncio
async def test_process_reminders_deduplication(db: AsyncSession, confirmed_user: dict, mocker):
    user_id = confirmed_user["id"]
    now = datetime.now(timezone.utc)

    # Create a task due in 1 hour (window: REMINDER_BEFORE)
    task = Task(
        title="Dedupe Task",
        user_id=user_id,
        due_date=now + timedelta(hours=1),
        completed=False
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Mock Celery tasks
    mock_push = mocker.patch("app.tasks.send_push_notification.delay")
    mock_email = mocker.patch("app.tasks.send_confirmation_email.delay")

    # 1. Run first time
    await _process_reminders_async()

    # Check notification created
    stmt = select(Notification).where(Notification.task_id == task.id)
    notifications = (await db.execute(stmt)).scalars().all()
    assert len(notifications) == 1
    assert mock_push.call_count == 1
    assert mock_email.call_count == 1

    # 2. Run second time - should NOT create another one
    await _process_reminders_async()
    notifications = (await db.execute(stmt)).scalars().all()
    assert len(notifications) == 1
    assert mock_push.call_count == 1 # Still 1
    assert mock_email.call_count == 1 # Still 1
