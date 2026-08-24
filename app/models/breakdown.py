"""Breakdown instrumentation model: one row per /breakdown request."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BreakdownAnswer(Base):
    """An instrumented breakdown call — mirrors PlanAnswer plus breakdown inputs.

    Stateless proposals: the raw LLM JSON (or "" for short-circuits) lives in
    ``answer``; ``context_task_id`` is set only for the per-task entry point.
    """

    __tablename__ = "tbl_breakdown_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    context_task_id: Mapped[int | None] = mapped_column(ForeignKey("tbl_tasks.id"), nullable=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(nullable=False)
    completion_tokens: Mapped[int] = mapped_column(nullable=False)
    total_tokens: Mapped[int] = mapped_column(nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0"))
    response_time_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    input_chars: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
