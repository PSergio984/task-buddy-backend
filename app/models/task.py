from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.tag import Tag
    from app.models.user import User

# Association table for Task <-> Tag
task_tags = Table(
    "tbl_task_tags",
    Base.metadata,
    Column("task_id", ForeignKey("tbl_tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tbl_tags.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, server_default=func.now()),
)


class Task(Base):
    __tablename__ = "tbl_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    user: Mapped[User] = relationship(back_populates="tasks")
    subtasks: Mapped[list[SubTask]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    tags: Mapped[list[Tag]] = relationship(
        secondary=task_tags, back_populates="tasks"
    )

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, title={self.title}, completed={self.completed})>"


class SubTask(Base):
    __tablename__ = "tbl_subtasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("tbl_tasks.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    task: Mapped[Task] = relationship(back_populates="subtasks")

    def __repr__(self) -> str:
        return f"<SubTask(id={self.id}, title={self.title}, completed={self.completed})>"
