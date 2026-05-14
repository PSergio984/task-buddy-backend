from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.crud import notification as notification_crud
from app.dependencies import get_db
from app.models.user import User
from app.schemas.notification import (
    NotificationRead,
    PushSubscriptionCreate,
    PushSubscriptionRead,
)
from app.security import get_confirmed_user

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    responses={
        401: {"description": "Not authenticated"},
    },
)

@router.get("/vapid-key")
async def get_vapid_key():
    """
    Get the VAPID public key for push notification subscription.
    """
    return {"public_key": config.VAPID_PUBLIC_KEY}

@router.get("/", response_model=list[NotificationRead])
async def list_notifications(
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    is_read: Optional[bool] = Query(None),
):
    """
    Retrieve notifications for the current user.
    """
    return await notification_crud.get_notifications(
        db, user_id=current_user.id, skip=skip, limit=limit, is_read=is_read
    )

@router.patch("/{notification_id}/read", response_model=NotificationRead)
async def mark_as_read(
    notification_id: int,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Mark a notification as read.
    """
    notification = await notification_crud.mark_notification_as_read(
        db, notification_id=notification_id, user_id=current_user.id
    )
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    await db.commit()
    await db.refresh(notification)
    return notification

@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_as_read(
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Mark all notifications as read for the current user.
    """
    await notification_crud.mark_all_notifications_as_read(db, user_id=current_user.id)
    await db.commit()

@router.post("/push-subscription", response_model=PushSubscriptionRead)
async def register_push_subscription(
    subscription: PushSubscriptionCreate,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Register or update a push subscription for the current user.
    """
    db_subscription = await notification_crud.create_or_update_push_subscription(
        db, user_id=current_user.id, subscription_in=subscription
    )
    await db.commit()
    await db.refresh(db_subscription)
    return db_subscription
