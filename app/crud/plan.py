"""CRUD operations for plan instrumentation rows."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.records import LLMCallRecord
from app.models.plan import PlanAnswer


async def create_plan_answer(
    db: AsyncSession,
    user_id: int,
    answer_text: str,
    record: LLMCallRecord,
    pool_size: int,
    available_minutes: int,
) -> PlanAnswer:
    """Persist one plan-instrumentation row (flush-not-commit; router commits)."""
    db_answer = PlanAnswer(
        user_id=user_id,
        answer=answer_text,
        model=record.model,
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        total_tokens=record.total_tokens,
        cost_usd=Decimal(str(record.cost)),
        response_time_ms=round(record.response_time * 1000, 2),
        pool_size=pool_size,
        available_minutes=available_minutes,
    )
    db.add(db_answer)
    await db.flush()
    await db.refresh(db_answer)
    return db_answer
