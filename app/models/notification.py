from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User

# JSONB on Postgres, plain JSON everywhere else (same variant as game.py).
JsonType = JSON().with_variant(JSONB(), "postgresql")


class NotificationType(str, enum.Enum):
    """Type of notification delivered to a user."""

    REMINDER_BEFORE = "REMINDER_BEFORE"
    REMINDER_DUE = "REMINDER_DUE"
    REMINDER_OVERDUE = "REMINDER_OVERDUE"
    SYSTEM = "SYSTEM"
    # Gamified-focus-layer kinds (issue #68). RECORD lands with #69 — the
    # enum member exists now so a second ALTER TYPE isn't needed.
    HABIT_REMINDER = "HABIT_REMINDER"
    DAILY_REMINDER = "DAILY_REMINDER"
    STREAK_RISK = "STREAK_RISK"
    LOW_HP = "LOW_HP"
    DAILY_MISSED = "DAILY_MISSED"
    DEATH = "DEATH"
    PHASE_END = "PHASE_END"
    LEVEL_UP = "LEVEL_UP"
    ACHIEVEMENT = "ACHIEVEMENT"
    RECORD = "RECORD"


class Notification(Base):
    """In-app notification shown to a user."""

    __tablename__ = "tbl_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tbl_tasks.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[NotificationType] = mapped_column(
        SQLEnum(NotificationType), default=NotificationType.SYSTEM, nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    action_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Dedup keys + entity links, e.g. {"habit_id": 5, "day": "2026-05-15",
    # "time": "07:30"} — game dispatch (#68) writes; NULL on legacy rows.
    meta: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped[User] = relationship(back_populates="notifications")
    task: Mapped[Task | None] = relationship()

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, title={self.title}, is_read={self.is_read})>"


class PushSubscription(Base):
    """Web push subscription registered by a user's browser."""

    __tablename__ = "tbl_push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped[User] = relationship(back_populates="push_subscriptions")

    def __repr__(self) -> str:
        return (
            f"<PushSubscription(id={self.id}, user_id={self.user_id}, "
            f"endpoint={self.endpoint[:20]}...)>"
        )
