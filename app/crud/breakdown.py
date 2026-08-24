"""CRUD operations for breakdown instrumentation rows."""

from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.records import LLMCallRecord
from app.models.breakdown import BreakdownAnswer


async def create_breakdown_answer(
    db: AsyncSession,
    user_id: int,
    answer_text: str,
    record: LLMCallRecord,
    input_chars: int,
    context_task_id: Optional[int] = None,
) -> BreakdownAnswer:
    """Persist one breakdown-instrumentation row (flush-not-commit; router commits)."""
    db_answer = BreakdownAnswer(
        user_id=user_id,
        context_task_id=context_task_id,
        answer=answer_text,
        model=record.model,
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        total_tokens=record.total_tokens,
        cost_usd=Decimal(str(record.cost)),
        response_time_ms=round(record.response_time * 1000, 2),
        input_chars=input_chars,
    )
    db.add(db_answer)
    await db.flush()
    await db.refresh(db_answer)
    return db_answer
