from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class Project(Base):
    __tablename__ = "tbl_projects"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_project_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    icon: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="projects")
    tasks: Mapped[list[Task]] = relationship(back_populates="project")

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name})>"
