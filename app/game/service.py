"""Event-ingestion orchestration: dedupe, order, score, persist.

One scoring path for every client — events arrive in batches (often queued
offline), are deduped on client_event_id, applied in client-timestamp order,
and committed transactionally by the router. On a mid-batch failure nothing
commits, so retrying the batch re-dedupes cleanly against the ledger.
"""

import random
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as game_crud
from app.game import (
    character_service,
    daily_service,
    engine,
    habit_service,
    notifications,
)
from app.game.engine import GameRates
from app.models.game import Daily, DailyItem, GameEvent, GameProfile, Habit
from app.schemas.game import GameEventIn, GameEventResult

_rng = random.Random()


async def load_rates(db: AsyncSession) -> GameRates:
    config_map = await game_crud.get_config_map(db)
    return GameRates.from_dict(config_map.get("economy", {}))


def _habit_for_event(event: GameEventIn, habits_by_id: dict[int, Habit]) -> Habit | None:
    """Resolve the habit a client habit_click targets; None = unresolvable.

    Only an int habit_id maps to a row — bool is excluded (True == 1 would
    silently resolve habit 1). Unresolvable ids (deleted/foreign/malformed)
    are recorded unscored — a client-claimed value can never reach the engine.
    """
    habit_id = event.payload.get("habit_id")
    if isinstance(habit_id, int) and not isinstance(habit_id, bool):
        return habits_by_id.get(habit_id)
    return None


def _daily_for_event(event: GameEventIn, dailies_by_id: dict[int, Daily]) -> Daily | None:
    """Resolve the daily a client daily_check targets; None = unresolvable.

    Same trust rule as _habit_for_event: only an owned row can score.
    """
    daily_id = event.payload.get("daily_id")
    if isinstance(daily_id, int) and not isinstance(daily_id, bool):
        return dailies_by_id.get(daily_id)
    return None


async def _daily_items(
    db: AsyncSession, daily_id: int, cache: dict[int, list[DailyItem]]
) -> list[DailyItem]:
    """Checklist rows for one daily, memoized across the batch."""
    if daily_id not in cache:
        cache[daily_id] = await game_crud.list_daily_items(db, [daily_id])
    return cache[daily_id]


async def _ingest_habit_click(
    db: AsyncSession,
    user_id: int,
    event: GameEventIn,
    habits_by_id: dict[int, Habit],
    profile: GameProfile,
    rates: GameRates,
    today,
    rng: random.Random,
    stat_bonus: dict[str, int],
) -> dict | None:
    """Score one synced habit_click (or record it unscored).

    Unresolvable habits, direction mismatches and a ValueError out of
    scoring (stored-but-corrupt state, e.g. a bogus difficulty reaching
    the engine) are recorded applied-but-unscored like score_check
    rejections — one poisoned row can't 400 the batch and wedge the
    client's retry queue. Returns the outcome (None when recorded
    unscored) so the caller can spot a mid-batch death that cost gear.
    """
    habit = _habit_for_event(event, habits_by_id)
    direction: str | None = event.payload.get("direction")
    unscored_reason: str | None = None
    outcome: dict | None = None
    if (
        habit is not None
        and direction in ("positive", "negative")
        and habit_service.direction_allows(habit, direction)
    ):
        try:
            outcome = await habit_service.score_click(
                db,
                habit,
                direction,
                profile,
                rates,
                today,
                eid=event.client_event_id,
                client_ts=event.client_ts,
                rng=rng,
                extra=event.payload,
                stat_bonus=stat_bonus,
            )
        except ValueError as exc:
            unscored_reason = str(exc)
    else:
        unscored_reason = "habit_unresolvable" if habit is None else "direction_mismatch"
    if unscored_reason is not None:
        # Record applied-but-unscored instead of scoring a claim the
        # server can't verify, or wedging the batch on a 400:
        # habit_unresolvable — no owned row (deleted/foreign/malformed
        # /missing id); direction_mismatch — the queued click predates
        # a direction PATCH or carries a malformed direction; a
        # ValueError out of scoring records the engine's message.
        # Consumer notes: the eid is permanently consumed — a client
        # correcting a rejected click must resend it under a NEW
        # client_event_id. Unscored rows keep client-claimed fields
        # (value/difficulty) at the same top-level keys that are
        # authoritative on scored rows — "_outcome.scored" is the
        # discriminator readers must check.
        db.add(
            GameEvent(
                user_id=user_id,
                client_event_id=event.client_event_id,
                type=event.type,
                payload={
                    **habit_service.clean_extra(event.payload),
                    "_outcome": {"scored": False, "reason": unscored_reason},
                },
                client_ts=event.client_ts,
            )
        )
    return outcome


async def _ingest_daily_check(
    db: AsyncSession,
    user_id: int,
    event: GameEventIn,
    dailies_by_id: dict[int, Daily],
    items_cache: dict[int, list[DailyItem]],
    profile: GameProfile,
    rates: GameRates,
    today,
    rng: random.Random,
    stat_bonus: dict[str, int],
) -> dict | None:
    """Score one synced daily_check (or record it unscored).

    The check day comes from the client's own timestamp — the same
    UTC-normalized axis the ledger sorts on. Unresolvable dailies/items and
    score_check rejections (daily_inactive / check_date_out_of_range /
    item_unresolvable) are recorded applied-but-unscored like habit failures,
    so the batch never wedges and the eid stays consumed.

    Returns the engine outcome (None when recorded unscored) so the caller
    can spot a mid-batch death that cost gear.
    """
    daily = _daily_for_event(event, dailies_by_id)
    item_id = event.payload.get("daily_item_id")
    unscored_reason: str | None = None
    outcome: dict | None = None
    if daily is None:
        unscored_reason = "daily_unresolvable"
    elif item_id is not None and (not isinstance(item_id, int) or isinstance(item_id, bool)):
        unscored_reason = "item_unresolvable"
    else:
        items = await _daily_items(db, daily.id, items_cache)
        # score_check validates lazily: a late ValueError (e.g. a bogus
        # difficulty in stored state) can fire AFTER it staged mark adds and
        # the streak bump — none flushed yet, so they sit in
        # session.new/dirty. Undo exactly that ORM state on rejection or the
        # "unscored" check would still land at the batch's commit. (No
        # savepoint: every raise path precedes score_check's flush, and an
        # outermost SAVEPOINT's release would commit early on aiosqlite's
        # deferred-BEGIN driver.)
        staged = set(db.new)
        dirty_before = set(db.dirty)
        try:
            outcome = await daily_service.score_check(
                db,
                daily,
                items,
                item_id,
                event.client_ts.date(),
                profile,
                rates,
                today,
                eid=event.client_event_id,
                client_ts=event.client_ts,
                rng=rng,
                extra=event.payload,
                done=event.payload.get("done"),
                stat_bonus=stat_bonus,
            )
        except ValueError as exc:
            for obj in set(db.new) - staged:
                db.expunge(obj)
            # Revert ONLY what this check dirtied (streak bump, flipped
            # marks) — objects dirty from earlier batch events keep their
            # pending rewards. refresh eagerly reloads the committed row,
            # discarding pending changes; a bare expire would instead
            # lazy-refresh → MissingGreenlet on the next event touching it.
            for obj in set(db.dirty) - dirty_before:
                await db.refresh(obj)
            unscored_reason = str(exc)
    if unscored_reason is not None:
        db.add(
            GameEvent(
                user_id=user_id,
                client_event_id=event.client_event_id,
                type=event.type,
                payload={
                    **habit_service.clean_extra(event.payload),
                    "_outcome": {"scored": False, "reason": unscored_reason},
                },
                client_ts=event.client_ts,
            )
        )
    return outcome


async def _apply_generic(
    db: AsyncSession,
    user_id: int,
    event: GameEventIn,
    profile: GameProfile,
    rates: GameRates,
    today,
    rng: random.Random,
    stat_bonus: dict[str, int],
) -> tuple[dict, dict[str, int]]:
    """Score one generic (non-habit/non-daily) event.

    A ValueError from the engine's payload guards records applied-but-
    unscored like the habit/daily paths — one malformed queued event must
    not 400 the batch and wedge the client's retry queue forever. Returns
    (outcome, stat_bonus) so a mid-batch death's gear loss stops scoring.
    """
    hp_before = profile.hp
    try:
        outcome = engine.apply_event(
            profile,
            event.type,
            event.payload,
            rates,
            rng_roll=rng.random(),
            rng=rng,
            today=today,
            stat_bonus=stat_bonus,
        )
    except ValueError as exc:
        return {"scored": False, "reason": str(exc)}, stat_bonus
    await character_service.resolve_death_gear(db, user_id, outcome, rng)
    await notifications.notify_score_outcome(db, user_id, profile, hp_before, outcome)
    if event.type == "focus_phase_completed" and outcome.get("scored"):
        await notifications.notify_phase_end(
            db, user_id, event.client_ts, event.payload.get("minutes")
        )
    stat_bonus = await _refresh_bonus_on_gear_loss(db, user_id, outcome, stat_bonus)
    return outcome, stat_bonus


async def _refresh_bonus_on_gear_loss(
    db: AsyncSession,
    user_id: int,
    outcome: dict | None,
    stat_bonus: dict[str, int],
) -> dict[str, int]:
    """Re-resolve equipped-stat totals when an outcome cost the user gear.

    The batch-level stat_bonus is a snapshot taken before the loop: a death
    that deletes an item mid-batch must not let its stats keep scoring
    later events (negative clicks and daily misses can kill, too).
    """
    if outcome is not None and outcome.get("gear_lost"):
        return await character_service.gear_stat_bonus(db, user_id)
    return stat_bonus


def _auto_distribute(profile: GameProfile) -> None:
    """Spend unspent points as each event lands — post_score's distribute
    step applied per event, so a mid-batch level-up feeds the NEXT event's
    stats and can't dodge the death cascade's stat pick. Cheap no-op when
    auto-allocation is off or nothing is pending."""
    if profile.auto_allocate:
        character_service.distribute_unspent(profile)


async def ingest_events(
    db: AsyncSession,
    user_id: int,
    events: list[GameEventIn],
    rng: random.Random | None = None,
) -> tuple[GameProfile, list[GameEventResult], GameRates]:
    """Apply a batch of client events; returns (profile, results, rates).

    Idempotent on client_event_id — both already-stored ids and repeats inside
    the same batch count as duplicates. Events apply in client_ts order
    (submission order breaks ties), so offline-reordered batches converge. The
    profile row is locked FOR UPDATE for the whole batch: concurrent syncs
    serialize instead of losing each other's totals.
    """
    rng = rng if rng is not None else _rng
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    rates = await load_rates(db)
    # One UTC day for the whole batch — a midnight-straddling ingest can't
    # split xp_today/gold_today counters across two dates.
    today = datetime.now(timezone.utc).date()
    seen = await game_crud.existing_event_ids(db, user_id, [e.client_event_id for e in events])
    # Keyed by original position: two entries sharing a client_event_id must
    # report applied-then-duplicate independently.
    status_by_idx: dict[int, Literal["applied", "duplicate"]] = {}
    ordered = sorted(enumerate(events), key=lambda t: (t[1].client_ts, t[0]))
    # One map serves both ends of the habit contract: click events resolve
    # stored state for drift, and scored focus phases auto-click bound habits.
    # Fetched only when the batch can touch habits.
    habits_by_id: dict[int, Habit] = {}
    if any(e.type in ("habit_click", "focus_phase_completed") for e in events):
        habits_by_id = {h.id: h for h in await game_crud.list_habits(db, user_id)}
    dailies_by_id: dict[int, Daily] = {}
    if any(e.type == "daily_check" for e in events):
        dailies_by_id = {d.id: d for d in await game_crud.list_dailies(db, user_id)}
    daily_items_cache: dict[int, list[DailyItem]] = {}
    bound_habits = [h for h in habits_by_id.values() if h.bind_focus]
    # One fanout budget per batch: bound habits x scored phase claims could
    # otherwise multiply into tens of thousands of writes inside this
    # profile-locked transaction (see habit_service.MAX_AUTO_CLICKS_PER_EVAL).
    auto_budget = habit_service.MAX_AUTO_CLICKS_PER_EVAL
    # Gear resolves once per batch — EXCEPT after a death that deletes an
    # item, which re-resolves below so the lost piece stops scoring.
    stat_bonus = await character_service.gear_stat_bonus(db, user_id)
    for idx, event in ordered:
        if event.client_event_id in seen:
            status_by_idx[idx] = "duplicate"
            continue
        if event.type == "habit_click":
            habit_outcome = await _ingest_habit_click(
                db,
                user_id,
                event,
                habits_by_id,
                profile,
                rates,
                today,
                rng,
                stat_bonus,
            )
            stat_bonus = await _refresh_bonus_on_gear_loss(db, user_id, habit_outcome, stat_bonus)
            _auto_distribute(profile)
            seen.add(event.client_event_id)
            status_by_idx[idx] = "applied"
            continue
        if event.type == "daily_check":
            daily_outcome = await _ingest_daily_check(
                db,
                user_id,
                event,
                dailies_by_id,
                daily_items_cache,
                profile,
                rates,
                today,
                rng,
                stat_bonus,
            )
            stat_bonus = await _refresh_bonus_on_gear_loss(db, user_id, daily_outcome, stat_bonus)
            _auto_distribute(profile)
            seen.add(event.client_event_id)
            status_by_idx[idx] = "applied"
            continue
        outcome, stat_bonus = await _apply_generic(
            db, user_id, event, profile, rates, today, rng, stat_bonus
        )
        # Engine outcome lands under "_outcome" so client payload keys never
        # collide with bookkeeping in the immutable ledger row. Client extras
        # are cleaned of server-reserved markers — a forged auto/session_id
        # can't masquerade a claimed event as server-authored metadata.
        payload = {**habit_service.clean_extra(event.payload), "_outcome": outcome}
        db.add(
            GameEvent(
                user_id=user_id,
                client_event_id=event.client_event_id,
                type=event.type,
                payload=payload,
                client_ts=event.client_ts,
            )
        )
        if event.type == "focus_phase_completed" and outcome.get("scored") and bound_habits:
            # Offline-run sessions trigger the same focus binding as the
            # server-side session engine (resolve #44: +click once per phase).
            auto_budget -= await habit_service.auto_click_bound(
                db,
                user_id,
                profile,
                rates,
                today,
                source_eid=event.client_event_id,
                client_ts=event.client_ts,
                rng=rng,
                habits=bound_habits,
                budget=auto_budget,
                stat_bonus=stat_bonus,
            )
        _auto_distribute(profile)
        seen.add(event.client_event_id)
        status_by_idx[idx] = "applied"
    if "applied" in status_by_idx.values():
        # Post-scoring hook (auto-distribute now, grant eval as it lands):
        # runs once per batch holding ≥1 applied event, under the profile lock.
        await character_service.post_score(
            db,
            user_id,
            profile,
            event_types={e.type for i, e in enumerate(events) if status_by_idx[i] == "applied"},
        )
    await db.flush()
    results = [
        GameEventResult(client_event_id=e.client_event_id, status=status_by_idx[i])
        for i, e in enumerate(events)
    ]
    return profile, results, rates
