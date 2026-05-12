from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from pywebpush import WebPushException
from sqlalchemy import select

from app.models.notification import Notification, PushSubscription
from app.models.task import Task
from app.tasks import (
    _process_reminders_async,
    _send_confirmation_email_async,
    _send_push_notification_async,
)


@pytest.mark.asyncio
async def test_send_push_notification_success(db, confirmed_user, mocker):
    user_id = confirmed_user["id"]
    # Create a subscription
    sub = PushSubscription(
        user_id=user_id,
        endpoint="https://example.com/push",
        p256dh="p256",
        auth="auth123"
    )
    db.add(sub)
    await db.commit()

    # Mock webpush
    mock_webpush = mocker.patch("app.tasks.webpush")
    mocker.patch("app.tasks.config.VAPID_PRIVATE_KEY", "test_key")

    await _send_push_notification_async(user_id, "Title", "Message", "/url")

    mock_webpush.assert_called_once()
    args, kwargs = mock_webpush.call_args
    assert kwargs["subscription_info"]["endpoint"] == "https://example.com/push"
    assert "Title" in kwargs["data"]
    assert "Message" in kwargs["data"]

@pytest.mark.asyncio
async def test_send_push_notification_410_gone(db, confirmed_user, mocker):
    user_id = confirmed_user["id"]
    endpoint = "https://example.com/expired"
    sub = PushSubscription(
        user_id=user_id,
        endpoint=endpoint,
        p256dh="p256",
        auth="auth123"
    )
    db.add(sub)
    await db.commit()

    # Mock webpush to raise 410
    mock_response = MagicMock()
    mock_response.status_code = 410
    mocker.patch("app.tasks.webpush", side_effect=WebPushException("Gone", response=mock_response))
    mocker.patch("app.tasks.config.VAPID_PRIVATE_KEY", "test_key")

    await _send_push_notification_async(user_id, "Title", "Message")

    # Verify subscription is deleted
    stmt = select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    res = await db.execute(stmt)
    assert res.scalar_one_or_none() is None

@pytest.mark.asyncio
async def test_process_reminders_triggers_channels(db, confirmed_user, mocker):
    user_id = confirmed_user["id"]
    now = datetime.now(timezone.utc)

    # Create a task due now
    task = Task(
        title="Due Now Task",
        user_id=user_id,
        due_date=now,
        completed=False
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Mock channels
    mock_push = mocker.patch("app.tasks.send_push_notification.delay")
    mock_email = mocker.patch("app.tasks.send_confirmation_email.delay")

    await _process_reminders_async()

    # Verify both channels triggered
    mock_push.assert_called_once()
    mock_email.assert_called_once()

    # Verify notification created in DB
    stmt = select(Notification).where(Notification.task_id == task.id)
    notifications = (await db.execute(stmt)).scalars().all()
    assert len(notifications) == 1

@pytest.mark.asyncio
async def test_send_confirmation_email_calls_brevo(mocker):
    mock_brevo = mocker.patch("app.tasks.send_brevo_email", return_value=MagicMock())

    await _send_confirmation_email_async("test@example.com", "Subject", "Body")

    mock_brevo.assert_called_once()
    args = mock_brevo.call_args[0]
    assert args[0] == "test@example.com"
    assert args[1] == "Subject"
    assert args[2] == "Body"
