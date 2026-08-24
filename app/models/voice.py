"""Voice instrumentation model: one row per /voice/plan request."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VoiceAnswer(Base):
    """An instrumented voice-plan call — transcript plus mirrored plan metrics.

    The transcript is observability only (pure trigger: it never modulates
    the plan). LLM columns mirror the PlanResponse metrics of the plan call
    this request triggered; ``llm_model="rule"`` with zeroed tokens marks a
    planner short-circuit.
    """

    __tablename__ = "tbl_voice_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    audio_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    stt_model: Mapped[str] = mapped_column(String, nullable=False)
    stt_latency_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    llm_model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(nullable=False)
    completion_tokens: Mapped[int] = mapped_column(nullable=False)
    total_tokens: Mapped[int] = mapped_column(nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0"))
    response_time_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    available_minutes: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
