from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.notification import NotificationType


class NotificationBase(BaseModel):
    """Common fields shared by notification schemas."""

    title: str
    message: str
    type: NotificationType = NotificationType.SYSTEM
    task_id: Optional[int] = None
    action_url: Optional[str] = None


class NotificationCreate(NotificationBase):
    """Payload for creating a notification."""

    user_id: int


class NotificationUpdate(BaseModel):
    """Payload for updating a notification."""

    is_read: bool


class NotificationRead(NotificationBase):
    """Notification as returned to the client."""

    id: int
    user_id: int
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PushSubscriptionBase(BaseModel):
    """Common fields shared by push subscription schemas."""

    endpoint: str
    p256dh: str
    auth: str


class PushSubscriptionCreate(PushSubscriptionBase):
    """Payload for registering a push subscription."""

    pass


class PushSubscriptionRead(PushSubscriptionBase):
    """Push subscription as returned to the client."""

    id: int
    user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
