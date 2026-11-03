"""Dailies orchestration: recurrence evaluation, check scoring, streaks.

One scoring path for every check — the endpoint's synchronous check and an
offline-synced daily_check event both land here. The stored Daily/DailyCheck
rows (never client-claimed ones) drive share and streak math; each check
writes back the day's completion state and lands a daily_check row in the
event ledger.

Recurrence contract (JSONB `Daily.recurrence`):
- {"kind": "daily"} — every day
- {"kind": "weekdays", "days": [0..6]} — specific weekdays, 0=Monday
- {"kind": "every_n_days", "interval": N, "anchor": "YYYY-MM-DD"} — every N
  days from the anchor (the write day when the client omits it)
- {"kind": "times_per_week", "count": C} — C completed days per ISO week
  (Mon–Sun); the scheduled unit is the week, keyed by its Sunday.
- Any kind may carry "since": "YYYY-MM-DD" — stamped by a schedule-changing
  PATCH; days before it ran under the old recurrence and are never
  evaluated under the new one.

Payout contract: a daily with N items pays each item check 1/N of the base
reward; the whole-daily (master) check pays the remaining fraction. The day
as a whole never pays more than the base amount — the scored ledger rows
(not the mutable checklist rows, which a PATCH can replace mid-day) are the
authoritative record of what the day already paid, and each check is
clamped to the residual share/xp/gold.

Checking the last open item auto-completes the master mark. Streak
increments once per completed schedulable day; the +1%/day gold bonus
applies to the post-increment streak.

shortcut: checks on non-scheduled days still pay full share (no streak
bump) — the spec is silent; Habitica only allows due-day checks. Flagged
on #63 for a product call.
"""

import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, TypeGuard

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as game_crud
from app.game import character_service, engine
from app.game.engine import GameRates
from app.game.habit_service import clean_extra
from app.models.game import Daily, DailyCheck, DailyItem, GameEvent, GameProfile

# Per-user cap — bounds the per-check item fanout and the sweep scan.
MAX_DAILIES_PER_USER = 100

# Sweep tunables — infra constants, deliberately not economy rates.
SWEEP_BATCH_SIZE = 200
GRACE_HOURS = 3  # a scheduled day is evaluated at next-day 03:00 UTC
LOOKBACK_DAYS = 35  # bounds post-downtime catch-up (~5 weekly units)
FREEZE_WINDOW_UNITS = 7  # one miss absorbed per rolling 7 scheduled units

_rng = random.Random()


# --- Recurrence (pure functions; malformed blobs evaluate to None) ---------


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _is_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_recurrence(raw: Any) -> dict | None:
    """Normalize a stored recurrence blob; None = malformed (sweep skips it).

    The write path validates through the schemas, but the stored JSONB is a
    trust boundary for the sweep: a bad blob must skip the daily, not crash
    the tick. A write-stamped `since` rides along normalized — it's the
    floor below which the current recurrence never evaluates.
    """
    if not isinstance(raw, dict):
        return None
    rec = _parse_schedule(raw)
    if rec is not None:
        since = _parse_date(raw.get("since"))
        if since is not None:
            rec["since"] = since
    return rec


def _parse_schedule(raw: dict) -> dict | None:
    """The schedule-defining fields of a recurrence blob; None = malformed."""
    kind = raw.get("kind")
    if kind == "daily":
        return {"kind": "daily"}
    if kind == "weekdays":
        days = raw.get("days")
        if not isinstance(days, list):
            return None
        clean = sorted({d for d in days if _is_int(d) and 0 <= d <= 6})
        if not clean:
            return None
        return {"kind": "weekdays", "days": clean}
    if kind == "every_n_days":
        interval = raw.get("interval")
        if not _is_int(interval) or not 1 <= interval <= 365:
            return None
        return {
            "kind": "every_n_days",
            "interval": interval,
            "anchor": _parse_date(raw.get("anchor")),
        }
    if kind == "times_per_week":
        count = raw.get("count")
        if not _is_int(count) or not 1 <= count <= 7:
            return None
        return {"kind": "times_per_week", "count": count}
    return None


def _schedule_signature(rec: dict | None) -> dict:
    """The schedule-defining keys of a normalized recurrence — `since` is
    write-path bookkeeping, not part of the schedule itself."""
    return {k: v for k, v in (rec or {}).items() if k != "since"}


def recurrence_for_storage(recurrence: dict, today: date, existing: dict | None = None) -> dict:
    """The blob persisted on write.

    The every_n_days anchor defaults to the write day so phase never
    silently depends on creation time; on PATCH (`existing` = the stored
    blob) a missing anchor preserves the stored one — re-anchoring to the
    PATCH day would silently shift the phase of a long-lived daily.

    A schedule-changing PATCH stamps `since` = the write day: days before
    it ran under the old recurrence — checks and misses there already
    stand — so the new rule never re-evaluates them. A schedule-identical
    PATCH carries a stored `since` forward instead of dropping it.
    """
    rec = dict(recurrence)
    rec.pop("since", None)
    if existing is None:
        # Create floors at the creation anchor — nothing to stamp.
        if rec.get("kind") == "every_n_days" and not rec.get("anchor"):
            rec["anchor"] = today.isoformat()
        return rec
    stored = parse_recurrence(existing)
    if rec.get("kind") == "every_n_days" and not rec.get("anchor"):
        rec["anchor"] = ((stored or {}).get("anchor") or today).isoformat()
    if _schedule_signature(parse_recurrence(rec)) != _schedule_signature(stored):
        rec["since"] = today.isoformat()
    elif stored is not None and stored.get("since") is not None:
        rec["since"] = stored["since"].isoformat()
    return rec


def daily_anchor(daily: Daily) -> date:
    """The daily's creation day (UTC) — the recurrence's base anchor."""
    return daily.created_at.date()


def effective_anchor(rec: dict, anchor: date) -> date:
    """The earliest day `rec` can schedule: the daily's creation anchor,
    raised by a PATCH-stamped `since` — days before the stamp ran under
    the old recurrence and are never re-evaluated."""
    since = _parse_date(rec.get("since"))
    return max(anchor, since) if since is not None else anchor


def week_end(day: date) -> date:
    """The ISO week's Sunday — the unit key for times_per_week recurrences."""
    return day + timedelta(days=6 - day.weekday())


def _first_week_unit(rec: dict, floor: date) -> date:
    """The first satisfiable times_per_week unit.

    A week whose schedulable span (floor→Sunday) holds fewer days than
    `count` can never be satisfied — checks are once/day — so scheduling
    it would manufacture an unavoidable miss. Skip that first unit; the
    partial week's days still accept checks (toward nothing). Resolves
    the product call flagged on #63 in the no-free-penalty direction.
    """
    first = week_end(floor)
    if (first - floor).days + 1 < rec["count"]:
        first += timedelta(days=7)
    return first


def is_schedulable(rec: dict, day: date, anchor: date) -> bool:
    """Whether `day` accepts check-ins / is a scheduled day for `rec`.

    times_per_week has no fixed days — every day at/after the anchor is a
    check-in day; its scheduled unit is the week, not the day. A stored
    `since` raises the floor: days before it belong to the old recurrence.
    """
    if day < effective_anchor(rec, anchor):
        return False
    kind = rec["kind"]
    if kind == "daily":
        return True
    if kind == "weekdays":
        return day.weekday() in rec["days"]
    if kind == "every_n_days":
        start = rec.get("anchor") or anchor
        if day < start:
            return False
        return bool((day - start).days % rec["interval"] == 0)
    if kind == "times_per_week":
        return True
    return False


def scheduled_units(rec: dict, anchor: date, start: date, end: date) -> list[date]:
    """Ordered scheduled-unit days in [start, end].

    For day-based recurrences the unit is the scheduled day itself; for
    times_per_week it is each week-end (Sunday) covering a week with at
    least one schedulable day.
    """
    if start > end:
        return []
    if rec["kind"] == "times_per_week":
        units = []
        d = max(week_end(start), _first_week_unit(rec, effective_anchor(rec, anchor)))
        while d <= end:
            units.append(d)
            d += timedelta(days=7)
        return units
    units = []
    day = start
    while day <= end:
        if is_schedulable(rec, day, anchor):
            units.append(day)
        day += timedelta(days=1)
    return units


def prior_units(rec: dict, anchor: date, unit: date, n: int) -> list[date]:
    """The n scheduled units immediately before `unit`, newest first —
    the rolling window the streak-freeze rule inspects."""
    out: list[date] = []
    floor = effective_anchor(rec, anchor)
    if rec["kind"] == "times_per_week":
        d = unit - timedelta(days=7)
        first = _first_week_unit(rec, floor)
        while len(out) < n and d >= first:
            out.append(d)
            d -= timedelta(days=7)
        return out
    d = unit - timedelta(days=1)
    scanned = 0
    # The scan cap covers the worst legal reach exactly: 6 units of an
    # every_n_days interval=365 recurrence need ~2190 day-steps. An older
    # anchor stops the walk first, so the cap only bounds the theoretical
    # far-tail.
    while len(out) < n and d >= floor and scanned < 2200:
        if is_schedulable(rec, d, anchor):
            out.append(d)
        d -= timedelta(days=1)
        scanned += 1
    return out


def eval_due(unit: date, now: datetime, grace_hours: int = GRACE_HOURS) -> bool:
    """Whether the unit's day-end + grace instant has passed."""
    deadline = datetime.combine(unit, time(0), tzinfo=timezone.utc) + timedelta(
        days=1, hours=grace_hours
    )
    return now >= deadline


# --- Check scoring ---------------------------------------------------------


def _zero_outcome(daily: Daily, **flags) -> dict:
    """A scored-but-unpaid outcome: state changed (restore/uncheck/all-paid
    master) without touching xp/gold — mirrors the engine's outcome keys so
    ledger readers see one shape."""
    return {
        "scored": True,
        "crit": False,
        "share": 0.0,
        "streak": daily.streak,
        "xp": 0,
        "levels_gained": 0,
        "gold": 0.0,
        **flags,
    }


async def _transition_marks(
    db: AsyncSession,
    daily: Daily,
    n_items: int,
    item_id: int | None,
    check_date: date,
    done: bool,
) -> tuple[float, bool, bool, str | None]:
    """Mutate the day's mark rows for one check/uncheck.

    Returns (share, first_completion, uncheck, reject_reason). The share is
    0 for restores and all-paid masters; first_completion marks the day's
    first transition to master-done (the only streak-bumping path);
    reject_reason is the applied-but-unscored vocabulary.
    """
    checks = await game_crud.list_daily_checks(db, [daily.id], check_date, check_date)
    marks = {c.daily_item_id: c for c in checks}
    master_mark = marks.get(None)
    master_was_done = master_mark is not None and master_mark.done
    done_item_ids = {k for k, c in marks.items() if k is not None and c.done}
    target = marks.get(item_id) if item_id is not None else master_mark
    share = 0.0
    first_completion = False
    uncheck = False
    reason: str | None = None
    if not done:
        if target is None or not target.done:
            reason = "nothing_to_uncheck"
        else:
            target.done = False
            uncheck = True
            if item_id is not None and master_mark is not None and master_mark.done:
                # An open item un-completes the day.
                master_mark.done = False
    elif master_was_done or (target is not None and target.done):
        reason = "already_checked"
    elif item_id is not None:
        if target is None:
            db.add(DailyCheck(daily_id=daily.id, daily_item_id=item_id, check_date=check_date))
            share = 1.0 / n_items
        else:
            target.done = True  # restore — the share already paid once
        # The target just transitioned to done either way (+1 vs the
        # pre-read done set).
        if len(done_item_ids) + 1 >= n_items:
            # Last open item — flip/insert the whole-daily mark so the day
            # reads completed to the sweep and to readers.
            if master_mark is None:
                db.add(DailyCheck(daily_id=daily.id, daily_item_id=None, check_date=check_date))
                first_completion = True
            else:
                master_mark.done = True
    else:
        if master_mark is None:
            db.add(DailyCheck(daily_id=daily.id, daily_item_id=None, check_date=check_date))
            first_completion = True
            # The whole-daily check pays the fraction items haven't.
            share = (n_items - len(done_item_ids)) / n_items if n_items else 1.0
        else:
            master_mark.done = True  # restore — already paid once
    return share, first_completion, uncheck, reason


async def _paid_totals(db: AsyncSession, daily: Daily, check_date: date) -> dict:
    """What this (daily, check_date) already paid — share/xp/gold summed
    over the day's scored daily_check ledger rows.

    The ledger, not checklist state, is the authoritative "paid so far":
    an items PATCH cascade-deletes the marks that used to prove it. A day's
    payout never exceeds the whole-check amount — every new check is
    clamped to the residual.
    """
    since = datetime.combine(check_date, time(0), tzinfo=timezone.utc)
    events = await game_crud.list_daily_check_events(db, daily.user_id, since)
    day_iso = check_date.isoformat()
    paid = {"share": 0.0, "xp": 0.0, "gold": 0.0}
    for ev in events:
        p = ev.payload or {}
        outcome = p.get("_outcome") or {}
        if (
            p.get("daily_id") != daily.id
            or p.get("check_date") != day_iso
            or not outcome.get("scored")
        ):
            continue
        paid["share"] += float(p.get("share") or 0.0)
        paid["xp"] += float(outcome.get("xp") or 0.0)
        paid["gold"] += float(outcome.get("gold") or 0.0)
    return paid


async def _apply_share(
    db: AsyncSession,
    daily: Daily,
    share: float,
    check_date: date,
    profile: GameProfile,
    rates: GameRates,
    today: date,
    rng: random.Random,
) -> tuple[dict, float]:
    """Clamp `share` to the day's unpaid residual and score it.

    Returns (outcome, effective_share) — the share actually paid, which the
    ledger stores so _paid_totals sums stay exact.
    """
    paid = await _paid_totals(db, daily, check_date)
    share = min(share, max(0.0, 1.0 - paid["share"]))
    if share <= 0:
        return _zero_outcome(daily), share
    outcome = engine.apply_event(
        profile,
        "daily_check",
        {
            "difficulty": daily.difficulty,
            "share": share,
            "streak": daily.streak,
            "paid_share": paid["share"],
            "paid_xp": paid["xp"],
            "paid_gold": paid["gold"],
        },
        rates,
        rng.random(),
        rng,
        today,
        stat_bonus=await character_service.gear_stat_bonus(db, daily.user_id),
    )
    await character_service.resolve_death_gear(db, daily.user_id, outcome, rng)
    return outcome, share


async def score_check(
    db: AsyncSession,
    daily: Daily,
    items: list[DailyItem],
    item_id: int | None,
    check_date: date,
    profile: GameProfile,
    rates: GameRates,
    today: date,
    *,
    eid: str,
    client_ts: datetime,
    rng: random.Random | None = None,
    extra: dict | None = None,
    done: bool | None = None,
) -> dict:
    """Apply one check/uncheck to a daily; write back state + ledger row.

    Callers hold the user's profile lock. ValueError reasons are the
    unscored-ledger vocabulary: daily_inactive, check_date_out_of_range,
    item_unresolvable, done_malformed — ingest records them on the stored
    row; the endpoint maps them to 400.

    Payout rules keep toggling un-farmable: a share pays once per
    (daily, item, day) — restoring an unchecked mark flips it back for share
    0, and the streak increments only on a day's FIRST completion (an
    uncheck never claws back rewards or streak; a same-day re-check
    restores without re-paying). Unchecking an item also un-marks the
    whole-day mark — the day is no longer complete.
    """
    rng = rng if rng is not None else _rng
    if done is None:
        done = True
    if not isinstance(done, bool):
        raise ValueError("done_malformed")
    if not daily.active:
        raise ValueError("daily_inactive")
    if check_date > today or check_date < daily_anchor(daily):
        raise ValueError("check_date_out_of_range")
    if item_id is not None and all(i.id != item_id for i in items):
        raise ValueError("item_unresolvable")

    share, first_completion, uncheck, reason = await _transition_marks(
        db, daily, len(items), item_id, check_date, done
    )
    rec = parse_recurrence(daily.recurrence)
    if (
        first_completion
        and rec is not None
        and is_schedulable(rec, check_date, daily_anchor(daily))
    ):
        # A unit the sweep already charged as missed can't retro-credit the
        # streak — the backfill check still pays share and marks completion.
        # times_per_week keys its misses at the week's Sunday (the unit), so
        # probe the unit containing check_date, not the raw day.
        miss_day = week_end(check_date) if rec["kind"] == "times_per_week" else check_date
        if await game_crud.get_daily_miss(db, daily.id, miss_day) is None:
            daily.streak += 1
    if reason is not None:
        outcome: dict = {"scored": False, "reason": reason}
    elif uncheck:
        outcome = _zero_outcome(daily, uncheck=True)
    else:
        outcome, share = await _apply_share(
            db, daily, share, check_date, profile, rates, today, rng
        )
    payload = {
        **clean_extra(extra),
        "daily_id": daily.id,
        "daily_item_id": item_id,
        "check_date": check_date.isoformat(),
        "done": done,
        "share": share,
        "streak": daily.streak,
        "_outcome": outcome,
    }
    db.add(
        GameEvent(
            user_id=daily.user_id,
            client_event_id=eid,
            type="daily_check",
            client_ts=client_ts,
            payload=payload,
        )
    )
    # autoflush is disabled project-wide: a same-batch follow-up event (e.g.
    # a queued uncheck) re-reads marks and must see this check's writes.
    await db.flush()
    return outcome
