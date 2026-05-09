from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.audit import AuditLog
    from app.models.group import Group
    from app.models.tag import Tag
    from app.models.task import Task


class User(Base):
    __tablename__ = "tbl_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed: Mapped[bool] = mapped_column(Boolean, server_default="0", default=False)
    confirmation_failed: Mapped[bool] = mapped_column(Boolean, server_default="0", default=False)

    # Relationships
    tasks: Mapped[list[Task]] = relationship(back_populates="user", cascade="all, delete-orphan")
    tags: Mapped[list[Tag]] = relationship(back_populates="user", cascade="all, delete-orphan")
    groups: Mapped[list[Group]] = relationship(back_populates="user", cascade="all, delete-orphan")
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, email={self.email})>"
