"""Plan instrumentation model: one row per /plan request (LLM or short-circuit)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PlanAnswer(Base):
    """An instrumented plan call — mirrors KnowledgeAnswer minus task_id/judge.

    A plan spans many tasks, so there is deliberately no task_id column; the
    raw LLM JSON (or "" for short-circuits) lives in ``answer``.
    """

    __tablename__ = "tbl_plan_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(nullable=False)
    completion_tokens: Mapped[int] = mapped_column(nullable=False)
    total_tokens: Mapped[int] = mapped_column(nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0"))
    response_time_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    pool_size: Mapped[int] = mapped_column(nullable=False, default=0)
    available_minutes: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
