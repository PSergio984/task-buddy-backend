"""Per-user daily LLM token budget (audit #29; ADR 0002).

The per-IP rate limit bounds call *count* but not *spend*: a legit-but-abusive
client can burn the provider's free-tier quota without a per-user cap.

Since ADR 0002 the cap is enforced with an atomic Postgres reservation
counter (``tbl_llm_usage_reservations``, keyed ``(user_id, UTC day)``):

- :func:`reserve_llm_budget` prepays a fixed per-endpoint estimate via one
  conditional UPDATE (compare-and-set) — zero rows updated ⇒ over budget.
- :func:`reconcile_llm_usage` adjusts the counter by ``actual - estimate``
  after a successful provider call.
- :func:`refund_llm_reservation` returns the estimate when the provider call
  aborts.

Commit-boundary exception: unlike the Phase-1 rule ("routers commit, CRUD
helpers flush"), this module deliberately ends ``reserve`` and ``refund``
with their own short ``await db.commit()`` — an open transaction would pin
the counter row lock across the multi-second provider call, which is exactly
the "locks held across the provider call" behavior ADR 0002 rejects.
``reconcile`` stays flush-only and rides the router's final commit.

Contributor convention (ADR 0002): every NEW LLM endpoint added to this app
MUST route its spend through ``reserve_llm_budget`` / ``reconcile_llm_usage``
/ ``refund_llm_reservation`` — never a fresh check-before-call SUM gate.
"""

import logging
from datetime import date, datetime, time, timezone

from sqlalchemy import CursorResult, Insert, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLM_DAILY_TOKEN_BUDGET
from app.models.breakdown import BreakdownAnswer
from app.models.budget import LlmUsageReservation
from app.models.knowledge import KnowledgeAnswer
from app.models.plan import PlanAnswer

logger = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    """Raised when the user's daily LLM token budget is exhausted (→ 429)."""


def _utc_today() -> date:
    """The UTC calendar day keying the reservation counter."""
    return datetime.combine(
        datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
    ).date()


async def daily_llm_tokens_used(db: AsyncSession, user_id: int) -> int:
    """Sum today's LLM tokens across ask + plan + breakdown instrumentation rows."""
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
    breakdown_total = (
        await db.execute(
            select(func.coalesce(func.sum(BreakdownAnswer.total_tokens), 0)).where(
                BreakdownAnswer.user_id == user_id,
                BreakdownAnswer.created_at >= start_of_day,
            )
        )
    ).scalar_one()
    return int(ask_total or 0) + int(plan_total or 0) + int(breakdown_total or 0)


async def check_llm_budget(db: AsyncSession, user_id: int) -> None:
    """Legacy check-before-call gate (superseded by the ADR 0002 reservation seam).

    Retained only until all call sites are rewired; new LLM endpoints must use
    :func:`reserve_llm_budget` instead of this SUM-based check.
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


async def reserve_llm_budget(db: AsyncSession, user_id: int, estimate: int) -> None:
    """Atomically prepay ``estimate`` tokens against today's daily cap (ADR 0002).

    Lazily creates today's counter row via ``ON CONFLICT DO NOTHING`` (the DB
    arbiters the two-first-requests-of-the-day race), then increments it with
    ONE conditional UPDATE — ``reserved_tokens + estimate <= cap``. Zero rows
    updated ⇒ the reservation would push past the cap ⇒ BudgetExceededError.

    Ends with its own ``await db.commit()`` BEFORE any provider call so no row
    lock survives into the LLM request. A cap ≤ 0 disables the gate entirely.
    """
    if LLM_DAILY_TOKEN_BUDGET <= 0:
        return
    utc_today = _utc_today()

    # Lazy first-of-day row creation, dialect-switched for SQLite tests vs
    # Postgres production (both expose on_conflict_do_nothing).
    bind = db.get_bind()
    lazy_create: Insert
    if bind.dialect.name == "postgresql":
        lazy_create = (
            postgres_insert(LlmUsageReservation)
            .values(user_id=user_id, day=utc_today, reserved_tokens=0)
            .on_conflict_do_nothing(index_elements=["user_id", "day"])
        )
    else:
        lazy_create = (
            sqlite_insert(LlmUsageReservation)
            .values(user_id=user_id, day=utc_today, reserved_tokens=0)
            .on_conflict_do_nothing(index_elements=["user_id", "day"])
        )
    await db.execute(lazy_create)

    # Compare-and-set increment (same shape as sync.py's proven CAS): the row
    # lock lives only for this statement's duration, never across an await on
    # the provider.
    result: CursorResult = await db.execute(  # type: ignore[assignment]
        update(LlmUsageReservation)
        .where(
            LlmUsageReservation.user_id == user_id,
            LlmUsageReservation.day == utc_today,
            LlmUsageReservation.reserved_tokens + estimate <= LLM_DAILY_TOKEN_BUDGET,
        )
        .values(reserved_tokens=LlmUsageReservation.reserved_tokens + estimate)
    )
    if result.rowcount == 0:
        logger.warning(
            "LLM daily budget exhausted user=%s day=%s estimate=%s cap=%s",
            user_id,
            utc_today,
            estimate,
            LLM_DAILY_TOKEN_BUDGET,
        )
        raise BudgetExceededError(
            f"daily LLM budget exhausted for user {user_id} on {utc_today}: "
            f"reserving {estimate} would exceed cap {LLM_DAILY_TOKEN_BUDGET}"
        )

    # Commit BEFORE the provider call — see the module commit-boundary note.
    await db.commit()


async def refund_llm_reservation(db: AsyncSession, user_id: int, estimate: int) -> None:
    """Return a prepaid ``estimate`` when the provider call aborts (ADR 0002).

    Unconditional keyed UPDATE — no CAS predicate needed because refunds fire
    only on paths that reserved moments earlier within the same request, and
    pairing with the reserve keeps the counter non-negative. Ends with its own
    ``await db.commit()`` exactly like :func:`reserve_llm_budget`. A missing
    counter row is logged and skipped — a refund failure must never mask the
    provider error being handled. A cap ≤ 0 disables the gate entirely.
    """
    if LLM_DAILY_TOKEN_BUDGET <= 0:
        return
    utc_today = _utc_today()
    result: CursorResult = await db.execute(  # type: ignore[assignment]
        update(LlmUsageReservation)
        .where(
            LlmUsageReservation.user_id == user_id,
            LlmUsageReservation.day == utc_today,
        )
        .values(reserved_tokens=LlmUsageReservation.reserved_tokens - estimate)
    )
    if result.rowcount == 0:
        logger.warning(
            "LLM reservation refund found no counter row user=%s day=%s estimate=%s",
            user_id,
            utc_today,
            estimate,
        )
        return
    await db.commit()


async def reconcile_llm_usage(db: AsyncSession, user_id: int, estimate: int, actual: int) -> None:
    """Reconcile today's reservation by the net delta ``actual - estimate``.

    Flush-style only — deliberately NO commit here; the update persists when
    the router performs its final commit. Raises BudgetExceededError if the
    counter row vanished mid-day (e.g. a downgrade ran) rather than silently
    dropping real spend. A cap ≤ 0 disables the gate entirely.
    """
    if LLM_DAILY_TOKEN_BUDGET <= 0:
        return
    utc_today = _utc_today()
    result: CursorResult = await db.execute(  # type: ignore[assignment]
        update(LlmUsageReservation)
        .where(
            LlmUsageReservation.user_id == user_id,
            LlmUsageReservation.day == utc_today,
        )
        .values(reserved_tokens=LlmUsageReservation.reserved_tokens + (actual - estimate))
    )
    if result.rowcount == 0:
        raise BudgetExceededError(
            f"cannot reconcile LLM usage: no reservation row for user {user_id} "
            f"on {utc_today} (estimate={estimate}, actual={actual})"
        )
