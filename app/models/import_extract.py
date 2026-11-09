"""Import instrumentation model: one row per /import/extract request."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ImportAnswer(Base):
    """An instrumented import-extraction call — mirrors BreakdownAnswer.

    Stateless proposals: the raw LLM JSON (or "" for short-circuits) lives in
    ``answer``; ``input_chars`` records the pasted-note length for the 10k
    cap's utilization signal.
    """

    __tablename__ = "tbl_import_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(nullable=False)
    completion_tokens: Mapped[int] = mapped_column(nullable=False)
    total_tokens: Mapped[int] = mapped_column(nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0"))
    response_time_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    input_chars: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_tbl_import_answers_user_created", "user_id", "created_at"),)
