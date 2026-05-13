from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class Tag(Base):
    __tablename__ = "tbl_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    icon: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped[User] = relationship(back_populates="tags")
    tasks: Mapped[list[Task]] = relationship(secondary="tbl_task_tags", back_populates="tags")

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tbl_tags_user_name"),)

    def __repr__(self) -> str:
        return f"<Tag(id={self.id}, name={self.name})>"
