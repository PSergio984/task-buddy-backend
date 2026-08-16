"""Tests for the REMINDER_BEFORE notification trigger."""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.models.task import Task
from app.tasks import _process_reminders_async


@pytest.mark.anyio
async def test_trigger_reminder_before_notification(
    db: AsyncSession, confirmed_user: dict[str, Any], mocker: Any
) -> None:
    """
    This test verifies that the REMINDER_BEFORE notification is generated
    for a task that is due exactly 60 minutes from now.
    """
    user_id = confirmed_user["id"]

    # The REMINDER_BEFORE window is [now + 50m, now + 70m].
    # Setting due_date to exactly 60 minutes from now.
    now = datetime.now(timezone.utc)
    due_in_1_hour = now + timedelta(minutes=60)

    # 1. Create a task that is due in 1 hour
    task = Task(
        title="Test Reminder Before Task", user_id=user_id, due_date=due_in_1_hour, completed=False
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Mock the async senders so the test doesn't send real push/email
    mocker.patch("app.tasks._send_push_notification_async")
    mocker.patch("app.tasks._send_confirmation_email_async")

    # 2. Trigger the reminder processing logic
    await _process_reminders_async()

    # 3. Verify that the REMINDER_BEFORE notification was created in the database
    stmt = select(Notification).where(
        Notification.task_id == task.id, Notification.type == NotificationType.REMINDER_BEFORE
    )
    notifications = (await db.execute(stmt)).scalars().all()

    # Assert exactly 1 notification was created
    assert len(notifications) == 1
    assert notifications[0].type == NotificationType.REMINDER_BEFORE
    assert "Test Reminder Before Task" in notifications[0].title
    assert "due in 1 hour" in notifications[0].message
