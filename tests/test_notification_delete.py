"""Tests for notification deletion."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


@pytest.mark.anyio
async def test_delete_notification(db: AsyncSession, confirmed_user: dict[str, Any]) -> None:
    """Verify a notification can be deleted."""
    user_id = confirmed_user["id"]

    # Create a notification
    notif = Notification(user_id=user_id, title="Test Title", message="Test Message", type="SYSTEM")
    db.add(notif)
    await db.commit()
    await db.refresh(notif)

    # Delete it
    from app.crud.notification import delete_notification

    deleted = await delete_notification(db, notif.id, user_id)
    await db.commit()

    assert deleted is True

    # Check it's gone
    stmt = select(Notification).where(Notification.id == notif.id)
    result = await db.execute(stmt)
    assert result.scalar_one_or_none() is None
