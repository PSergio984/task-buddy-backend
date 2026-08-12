"""Task-attached knowledge models: notes, instrumented answers, and feedback."""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# JSONB on Postgres, plain JSON everywhere else (SQLite test DB cannot compile JSONB).
JsonType = JSON().with_variant(JSONB(), "postgresql")


class SourceType(str, enum.Enum):
    """Where a knowledge row's content came from. Text notes first; file/url later."""

    NOTE = "note"


class JudgeVerdict(str, enum.Enum):
    """Relevance verdict produced by the LLM-as-judge."""

    RELEVANT = "RELEVANT"
    PARTLY_RELEVANT = "PARTLY_RELEVANT"
    NON_RELEVANT = "NON_RELEVANT"


class TaskKnowledge(Base):
    """A user-owned piece of knowledge attached to a task (a note, initially)."""

    __tablename__ = "tbl_knowledge"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    # CASCADE: TaskKnowledge has no ORM relationship on Task (unlike SubTask's
    # delete-orphan cascade), so task deletion must cascade at the DB level.
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_tasks.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[SourceType] = mapped_column(
        SQLEnum(SourceType), default=SourceType.NOTE, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Mapped attribute is extra_metadata because "metadata" is reserved by
    # SQLAlchemy's Declarative API; the DB column stays named "metadata".
    extra_metadata: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<TaskKnowledge(id={self.id}, task_id={self.task_id})>"


class KnowledgeAnswer(Base):
    """An instrumented answer produced by the knowledge assistant."""

    __tablename__ = "tbl_knowledge_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_tasks.id", ondelete="CASCADE"), nullable=False
    )
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(nullable=False)
    completion_tokens: Mapped[int] = mapped_column(nullable=False)
    total_tokens: Mapped[int] = mapped_column(nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0"))
    response_time_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    # Citations: [{knowledge_id, chunk_text, rrf_score}]
    retrieved_chunks: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)
    judge_verdict: Mapped[JudgeVerdict | None] = mapped_column(SQLEnum(JudgeVerdict), nullable=True)
    judge_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KnowledgeFeedback(Base):
    """User +1/-1 feedback on a knowledge answer."""

    __tablename__ = "tbl_knowledge_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("tbl_knowledge_answers.id", ondelete="CASCADE"), nullable=False
    )
    # rating is +1 or -1 (user thumbs up/down on an answer)
    rating: Mapped[int] = mapped_column(nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
