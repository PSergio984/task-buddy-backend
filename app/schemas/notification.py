from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.notification import NotificationType


class NotificationBase(BaseModel):
    title: str
    message: str
    type: NotificationType = NotificationType.SYSTEM
    task_id: Optional[int] = None
    action_url: Optional[str] = None


class NotificationCreate(NotificationBase):
    user_id: int


class NotificationUpdate(BaseModel):
    is_read: bool


class NotificationRead(NotificationBase):
    id: int
    user_id: int
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PushSubscriptionBase(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


class PushSubscriptionCreate(PushSubscriptionBase):
    pass


class PushSubscriptionRead(PushSubscriptionBase):
    id: int
    user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
