"""Daily-miss evaluation sweep (issue #63, ADR 0001).

One lifespan-driven tick scans active dailies and evaluates every scheduled
unit whose day-end + grace instant has passed: a unit left unchecked records
a DailyMiss row, costs HP through the engine, and emits a daily_missed
ledger event; one miss per rolling 7 scheduled units is absorbed by the
streak freeze (streak preserved, HP still applies).

Idempotent across overlapping deploys: the (daily_id, scheduled_day) unique
constraint on tbl_daily_misses is the dedupe anchor. Two instances evaluate
the same unit; whoever commits the miss row first wins, and the loser's
savepoint-rolled insert skips all scoring. Correctness lives in Postgres —
no process-memory state. Users have no timezone field yet, so day-ends are
evaluated in UTC (the documented fallback).
"""

import logging
import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crud import game as game_crud
from app.game import daily_service, engine
from app.game.service import load_rates
from app.models.game import Daily, DailyMiss, GameEvent, GameProfile

logger = logging.getLogger(__name__)

_rng = random.Random()


def _unit_satisfied(rec: dict, unit: date, done_days: set[date], anchor: date) -> bool:
    """Whether the unit already counts as completed.

    Day-based units need their own whole-daily mark; a times_per_week unit
    needs `count` distinct completed days inside its ISO week.
    """
    if rec["kind"] == "times_per_week":
        week_start = unit - timedelta(days=6)
        return bool(
            sum(1 for d in done_days if week_start <= d <= unit and d >= anchor) >= rec["count"]
        )
    return unit in done_days


async def _evaluate_daily(
    db: AsyncSession,
    daily: Daily,
    now: datetime,
    today: date,
    rates,
) -> int:
    """Evaluate all due units of one daily; return misses recorded."""
    rec = daily_service.parse_recurrence(daily.recurrence)
    if rec is None:
        logger.warning("daily %s has malformed recurrence; sweep skipped it", daily.id)
        return 0
    anchor = daily_service.daily_anchor(daily)
    window_start = max(anchor, today - timedelta(days=daily_service.LOOKBACK_DAYS))
    units = [
        u
        for u in daily_service.scheduled_units(rec, anchor, window_start, today)
        if daily_service.eval_due(u, now)
    ]
    if not units:
        return 0
    checks = await game_crud.list_daily_checks(db, [daily.id], window_start, today)
    done_days = {c.check_date for c in checks if c.daily_item_id is None and c.done}
    miss_rows = await game_crud.list_daily_misses(db, daily.id, window_start)
    missed_days = {m.scheduled_day for m in miss_rows}
    profile: GameProfile | None = None
    profile_fetched = False
    recorded = 0
    for unit in units:
        if unit in missed_days or _unit_satisfied(rec, unit, done_days, anchor):
            continue
        prior = daily_service.prior_units(rec, anchor, unit, daily_service.FREEZE_WINDOW_UNITS - 1)
        # One miss per rolling 7 scheduled units is frozen: a miss in the
        # prior 6 units means this one breaks the streak.
        frozen = not any(u in missed_days for u in prior)
        miss = DailyMiss(
            daily_id=daily.id, user_id=daily.user_id, scheduled_day=unit, frozen=frozen
        )
        try:
            # The insert IS the cross-instance claim: the loser of a racing
            # pair hits the unique constraint, rolls back to the savepoint,
            # and scores nothing.
            async with db.begin_nested():
                db.add(miss)
                await db.flush()
        except IntegrityError:
            missed_days.add(unit)
            continue
        missed_days.add(unit)
        if not profile_fetched:
            # Lazily — a daily whose owner lacks a profile row still records
            # the miss/streak change; only HP loss needs the row. FOR UPDATE
            # matches every other scoring path's serialization point.
            profile_fetched = True
            profile = (
                await db.execute(
                    select(GameProfile)
                    .where(GameProfile.user_id == daily.user_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
        outcome: dict = {"scored": False}
        if profile is not None:
            outcome = engine.apply_event(
                profile,
                "daily_missed",
                {"difficulty": daily.difficulty},
                rates,
                _rng.random(),
                _rng,
                today,
            )
        streak_before = daily.streak
        if not frozen:
            daily.streak = 0
        miss.hp_lost = float(outcome.get("hp_lost", 0.0))
        outcome = {
            **outcome,
            "frozen": frozen,
            "streak_before": streak_before,
            "streak_after": daily.streak,
        }
        db.add(
            GameEvent(
                user_id=daily.user_id,
                # Deterministic server id — the ledger uq is the backstop if
                # a miss row ever survives without its event (crash between
                # flush and commit replays cleanly: the whole unit retries).
                client_event_id=f"server:daily:{daily.id}:missed:{unit.isoformat()}",
                type="daily_missed",
                client_ts=now,
                payload={
                    "daily_id": daily.id,
                    "scheduled_day": unit.isoformat(),
                    "frozen": frozen,
                    "_outcome": outcome,
                },
            )
        )
        recorded += 1
    await db.flush()
    return recorded


async def run_daily_miss_sweep(
    now: datetime | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """One sweep tick over all active dailies; returns misses recorded.

    `now` and `session_factory` are injectable for tests — day-ends are
    evaluated in UTC until a user timezone field exists (issue #63
    documented fallback).
    """
    if session_factory is None:
        from app.database import AsyncSessionLocal

        session_factory = AsyncSessionLocal
    now = now or datetime.now(timezone.utc)
    today = now.date()
    recorded = 0
    async with session_factory() as db:
        rates = await load_rates(db)
        last_id = 0
        while True:
            batch = await game_crud.list_active_dailies(db, last_id, daily_service.SWEEP_BATCH_SIZE)
            if not batch:
                break
            last_id = batch[-1].id
            for daily in batch:
                # Hoisted: a mid-evaluation rollback expires the ORM object —
                # touching daily.id in the handler would lazy-load.
                daily_id = daily.id
                try:
                    recorded += await _evaluate_daily(db, daily, now, today, rates)
                except Exception:
                    # One bad daily can't wedge the tick — its miss rows are
                    # uncommitted so the unit retries next pass.
                    await db.rollback()
                    logger.exception("daily miss evaluation failed for daily=%s", daily_id)
                    continue
                await db.commit()
    return recorded
