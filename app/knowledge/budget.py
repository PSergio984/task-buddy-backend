"""Per-user daily LLM token budget (audit #29).

The per-IP rate limit bounds call *count* but not *spend*: a legit-but-abusive
client can burn the provider's free-tier quota without a per-user cap. This
module checks today's instrumented token totals (ask + plan rows) against the
configured daily budget before any LLM call is made.
"""

import logging
from datetime import datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLM_DAILY_TOKEN_BUDGET
from app.models.knowledge import KnowledgeAnswer
from app.models.plan import PlanAnswer

logger = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    """Raised when the user's daily LLM token budget is exhausted (→ 429)."""


async def daily_llm_tokens_used(db: AsyncSession, user_id: int) -> int:
    """Sum today's LLM tokens across ask + plan instrumentation rows."""
    start_of_day = datetime.combine(
        datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
    )
    ask_total = (
        await db.execute(
            select(func.coalesce(func.sum(KnowledgeAnswer.total_tokens), 0)).where(
                KnowledgeAnswer.user_id == user_id,
                KnowledgeAnswer.created_at >= start_of_day,
            )
        )
    ).scalar_one()
    plan_total = (
        await db.execute(
            select(func.coalesce(func.sum(PlanAnswer.total_tokens), 0)).where(
                PlanAnswer.user_id == user_id,
                PlanAnswer.created_at >= start_of_day,
            )
        )
    ).scalar_one()
    return int(ask_total or 0) + int(plan_total or 0)


async def check_llm_budget(db: AsyncSession, user_id: int) -> None:
    """Raise ``BudgetExceededError`` when the user is at/over the daily cap.

    A budget of 0 (or negative) disables the cap entirely. Must be called
    BEFORE any LLM call so over-budget users never incur spend.
    """
    if LLM_DAILY_TOKEN_BUDGET <= 0:
        return
    used = await daily_llm_tokens_used(db, user_id)
    if used >= LLM_DAILY_TOKEN_BUDGET:
        logger.warning(
            "LLM daily budget exhausted user=%s used=%s limit=%s",
            user_id,
            used,
            LLM_DAILY_TOKEN_BUDGET,
        )
        raise BudgetExceededError(f"daily LLM budget exhausted: {used} >= {LLM_DAILY_TOKEN_BUDGET}")
