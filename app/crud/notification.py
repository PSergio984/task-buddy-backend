from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, PushSubscription
from app.schemas.notification import NotificationCreate, PushSubscriptionCreate


async def get_notifications(
    db: AsyncSession, user_id: int, skip: int = 0, limit: int = 100, is_read: Optional[bool] = None
) -> list[Notification]:
    """
    List user notifications with pagination and filtering.
    """
    query = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .offset(skip)
        .limit(limit)
        .order_by(Notification.created_at.desc())
    )
    if is_read is not None:
        query = query.where(Notification.is_read == is_read)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_notification(db: AsyncSession, notification_in: NotificationCreate) -> Notification:
    """
    Create a new notification.
    """
    db_notification = Notification(**notification_in.model_dump())
    db.add(db_notification)
    await db.flush()
    return db_notification


async def mark_notification_as_read(
    db: AsyncSession, notification_id: int, user_id: int
) -> Optional[Notification]:
    """
    Mark a specific notification as read.
    """
    query = select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    result = await db.execute(query)
    db_notification = result.scalar_one_or_none()
    if db_notification:
        db_notification.is_read = True
        db.add(db_notification)
        await db.flush()
    return db_notification


async def create_or_update_push_subscription(
    db: AsyncSession, user_id: int, subscription_in: PushSubscriptionCreate
) -> PushSubscription:
    """
    UPSERT logic for push subscriptions (match on endpoint).
    """
    query = select(PushSubscription).where(PushSubscription.endpoint == subscription_in.endpoint)
    result = await db.execute(query)
    db_subscription = result.scalar_one_or_none()

    if db_subscription:
        # Update existing
        db_subscription.p256dh = subscription_in.p256dh
        db_subscription.auth = subscription_in.auth
        db_subscription.user_id = user_id
    else:
        # Create new
        db_subscription = PushSubscription(**subscription_in.model_dump(), user_id=user_id)

    db.add(db_subscription)
    await db.flush()
    return db_subscription


async def delete_push_subscription(db: AsyncSession, endpoint: str) -> None:
    """
    Remove an invalid subscription (needed for 410 Gone handling later).
    """
    stmt = delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
    await db.execute(stmt)
    await db.flush()
