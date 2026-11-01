"""Daily-miss evaluation sweep (issue #63, ADR 0001).

One lifespan-driven tick scans active dailies and evaluates every scheduled
unit whose day-end + grace instant has passed: a unit left unchecked records
a DailyMiss row, costs HP through the engine, and emits a daily_missed
ledger event; one miss per rolling 7 scheduled units is absorbed by the
streak freeze (streak preserved, HP still applies).

Idempotent across overlapping deploys: the (daily_id, scheduled_day) unique
constraint on tbl_daily_misses is the dedupe anchor. Two instances evaluate
the same unit; whoever commits the miss row first wins, and the loser's
insert conflicts — its unit transaction rolls back and it moves on to the
next unit. Correctness lives in Postgres — no process-memory state. Users
have no timezone field yet, so day-ends are evaluated in UTC (the
documented fallback).

shortcut: an `active` gap is invisible to evaluation — a daily re-enabled
after N days is evaluated across the whole lookback window in one tick
(up to ~35 misses + HP). Spec is silent; flagged on #63 for a product call.
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


async def _evaluate_unit(
    db: AsyncSession,
    daily: Daily,
    unit: date,
    rec: dict,
    anchor: date,
    missed_days: set[date],
    done_days: set[date],
    now: datetime,
    today: date,
    rates,
) -> bool:
    """Claim + score one due unit, committed as its own transaction.

    True = miss recorded; False = the unit rolled back — either a racing
    instance claimed it first (`missed_days` updated here) or a check
    committed mid-eval (`done_days` updated here). Either way `daily` is
    left expired and the caller re-reads it before the next unit. Claim
    insert, scoring and ledger row land atomically, and a later unit's
    failure can't take this one back. (A savepoint can't express this on
    aiosqlite: the driver's implicit BEGIN only materializes on the first
    DML, so an outermost SAVEPOINT's RELEASE would commit outright.)
    """
    # One miss per rolling 7 scheduled units is frozen: a miss in the
    # prior 6 units means this one breaks the streak.
    frozen = not any(
        u in missed_days
        for u in daily_service.prior_units(rec, anchor, unit, daily_service.FREEZE_WINDOW_UNITS - 1)
    )
    miss = DailyMiss(daily_id=daily.id, user_id=daily.user_id, scheduled_day=unit, frozen=frozen)
    # The insert IS the cross-instance claim. This flush emits ONLY the
    # miss row — every other write is committed per-unit below — so an
    # IntegrityError unambiguously means a racing instance committed this
    # unit first. (Postgres aborts a conflicted transaction, so the unit
    # must roll back rather than retry inside it.)
    db.add(miss)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        missed_days.add(unit)
        return False
    missed_days.add(unit)
    # A check committing between the daily pre-read and this claim would
    # land a day that's both missed (HP + streak reset) and done — re-read
    # satisfaction inside the unit transaction before committing the miss.
    fresh_from = unit - timedelta(days=6) if rec["kind"] == "times_per_week" else unit
    fresh_checks = await game_crud.list_daily_checks(db, [daily.id], fresh_from, unit)
    fresh_done = {c.check_date for c in fresh_checks if c.daily_item_id is None and c.done}
    if _unit_satisfied(rec, unit, fresh_done, anchor):
        await db.rollback()
        done_days.update(fresh_done)
        return False
    # FOR UPDATE serializes against a racing claim's scoring — two
    # instances can win different units of the same daily, and the profile
    # lock makes their HP losses additive, not lost-update.
    profile = (
        await db.execute(
            select(GameProfile).where(GameProfile.user_id == daily.user_id).with_for_update()
        )
    ).scalar_one_or_none()
    # A daily whose owner lacks a profile row still records the
    # miss/streak change; only HP loss needs the row.
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
            # Deterministic server id — the ledger uq is the backstop if a
            # miss row ever survives without its event (crash between flush
            # and commit replays cleanly: the whole unit retries).
            # shortcut: out-of-band deletion of a miss row while its event
            # survives re-claims the unit, then wedges on this eid's uq at
            # commit (per-daily rollback, retried forever) — admin cleanup
            # must remove both rows or neither.
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
    # Per-unit commit: the claim, scoring and event land atomically, and a
    # later unit's failure can't take this one back.
    await db.commit()
    return True


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
    # Snapshot the id now: a rollback below expires `daily`, and touching
    # an expired attribute raises MissingGreenlet mid-loop.
    daily_id = daily.id
    anchor = daily_service.daily_anchor(daily)
    window_start = max(anchor, today - timedelta(days=daily_service.LOOKBACK_DAYS))
    units = [
        u
        for u in daily_service.scheduled_units(rec, anchor, window_start, today)
        if daily_service.eval_due(u, now)
    ]
    if not units:
        return 0
    checks = await game_crud.list_daily_checks(db, [daily_id], window_start, today)
    done_days = {c.check_date for c in checks if c.daily_item_id is None and c.done}
    # Freeze evidence must reach back 6 *scheduled units*, which for sparse
    # recurrences (a weekday slot is ~7 days apart, every_n_days further)
    # extends well past the lookback window — load misses from the earliest
    # consultable prior unit or old misses go unseen and a freeze is granted
    # that wasn't earned.
    miss_since = window_start
    for u in units:
        priors = daily_service.prior_units(rec, anchor, u, daily_service.FREEZE_WINDOW_UNITS - 1)
        if priors:
            miss_since = min(miss_since, priors[-1])
    miss_rows = await game_crud.list_daily_misses(db, daily_id, miss_since)
    missed_days = {m.scheduled_day for m in miss_rows}
    recorded = 0
    for unit in units:
        if unit in missed_days or _unit_satisfied(rec, unit, done_days, anchor):
            continue
        # `daily` is re-read only after a rollback — its attributes (e.g.
        # difficulty for scoring) can go stale across the unit commits if a
        # PATCH lands mid-eval; harmless, next tick's pass self-corrects.
        if await _evaluate_unit(
            db, daily, unit, rec, anchor, missed_days, done_days, now, today, rates
        ):
            recorded += 1
            continue
        # Rolled back (lost claim or a check landed mid-eval) — `daily` is
        # expired; re-read it for the next unit. A mid-tick
        # delete/deactivate ends this evaluation early.
        fresh = await db.get(Daily, daily_id, populate_existing=True)
        if fresh is None or not fresh.active:
            return recorded
        daily = fresh
    return recorded


async def run_daily_miss_sweep(
    now: datetime | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """One sweep tick over all active dailies; returns misses recorded.

    `now` and `session_factory` are injectable for tests — day-ends are
    evaluated in UTC until a user timezone field exists (issue #63
    documented fallback).

    Per-daily fault isolation: a failed evaluation rolls the whole session
    back, which EXPIRES every loaded object (rollback is not
    dirty-only, and expire_on_commit does not apply). Iterating
    pre-fetched rows after a failure would lazy-refresh expired attributes
    and raise MissingGreenlet, killing the tick — so the loop walks plain
    int ids and re-reads each Daily with populate_existing inside the try.
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
            batch_ids = await game_crud.list_active_daily_ids(
                db, last_id, daily_service.SWEEP_BATCH_SIZE
            )
            if not batch_ids:
                break
            last_id = batch_ids[-1]
            for daily_id in batch_ids:
                try:
                    # populate_existing: unconditional fresh read — an
                    # identity-map hit on a post-rollback expired object
                    # would otherwise raise MissingGreenlet on first access.
                    daily = await db.get(Daily, daily_id, populate_existing=True)
                    if daily is None or not daily.active:
                        continue  # deleted or deactivated mid-tick
                    recorded += await _evaluate_daily(db, daily, now, today, rates)
                    # Inside the try: a commit-level failure (deadlock, lost
                    # connection) takes the same per-daily recovery path.
                    await db.commit()
                except Exception:
                    # One bad daily can't wedge the tick — its miss rows are
                    # uncommitted so the unit retries next pass.
                    await db.rollback()
                    logger.exception("daily miss evaluation failed for daily=%s", daily_id)
                    continue
    return recorded
