"""LLM budget reservation model: one counter row per (user, UTC day)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LlmUsageReservation(Base):
    """Prepaid daily LLM token counter (ADR 0002).

    One row per ``(user_id, day)`` lazily created on the user's first reserve
    of the UTC day (``ON CONFLICT DO NOTHING`` makes the database the arbiter
    of the creation race). ``reserved_tokens`` accumulates prepaid estimates;
    enforcement is a single conditional UPDATE (compare-and-set) executed by
    :mod:`app.knowledge.budget`, so concurrent requests can never push the
    counter past the configured cap.
    """

    __tablename__ = "tbl_llm_usage_reservations"
    __table_args__ = (
        UniqueConstraint("user_id", "day", name="uq_tbl_llm_usage_reservations_user_day"),
        Index("ix_tbl_llm_usage_reservations_user_day", "user_id", "day"),
        CheckConstraint("reserved_tokens >= 0", name="ck_tbl_llm_usage_reservations_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
