from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.tag import Tag
    from app.models.user import User


class TaskPriority(str, enum.Enum):
    """Priority level of a task."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DeadlineType(str, enum.Enum):
    """Deadline kind: soft (auto-proposed) or hard (user-set).

    Wire format uses values ("soft"/"hard"), not member names — the migration
    enum and API wire format both use values (SourceType precedent).
    """

    SOFT = "soft"
    HARD = "hard"


# Association table for Task <-> Tag
task_tags = Table(
    "tbl_task_tags",
    Base.metadata,
    Column("task_id", ForeignKey("tbl_tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tbl_tags.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


class Task(AsyncAttrs, Base):
    """Top-level to-do item owned by a user."""

    __tablename__ = "tbl_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("tbl_projects.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[TaskPriority] = mapped_column(
        SQLEnum(TaskPriority), default=TaskPriority.MEDIUM, nullable=False
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_effort_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline_type: Mapped[DeadlineType | None] = mapped_column(
        SQLEnum(DeadlineType, values_callable=lambda members: [m.value for m in members]),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Transient (D-02): soft-deadline proposal — response-only, never
    # persisted. Unannotated so SQLAlchemy never maps it to a column; the
    # property exposes it for pydantic from_attributes.
    _proposed_deadline = None

    @property
    def proposed_deadline(self) -> datetime | None:
        return self._proposed_deadline

    @proposed_deadline.setter
    def proposed_deadline(self, value: datetime | None) -> None:
        self._proposed_deadline = value

    # Relationships
    user: Mapped[User] = relationship(back_populates="tasks")
    project: Mapped[Project | None] = relationship(back_populates="tasks")
    subtasks: Mapped[list[SubTask]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="SubTask.position"
    )
    tags: Mapped[list[Tag]] = relationship(secondary=task_tags, back_populates="tasks")

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, title={self.title}, completed={self.completed})>"


class SubTask(Base):
    """Sub-task nested underneath a parent task."""

    __tablename__ = "tbl_subtasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("tbl_tasks.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    task: Mapped[Task] = relationship(back_populates="subtasks")

    def __repr__(self) -> str:
        return f"<SubTask(id={self.id}, title={self.title}, completed={self.completed})>"
