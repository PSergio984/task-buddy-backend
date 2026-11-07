"""Event-ingestion orchestration: dedupe, order, score, persist.

One scoring path for every client — events arrive in batches (often queued
offline), are deduped on client_event_id, applied in client-timestamp order,
and committed transactionally by the router. On a mid-batch failure nothing
commits, so retrying the batch re-dedupes cleanly against the ledger.
"""

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as game_crud
from app.game import (
    character_service,
    daily_service,
    engine,
    habit_service,
    notifications,
    phone_down,
)
from app.game.engine import GameRates
from app.models.game import Daily, DailyItem, FocusSession, GameEvent, GameProfile, Habit
from app.schemas.game import GameEventIn, GameEventResult

_rng = random.Random()

# Blob growth bound (#70): every applied span lands on the session row's
# JSON forever, so an unbounded count lets a client inflate one row without
# limit. Over the cap the event records unscored like any rejection.
# Sibling bound of the penalized_violation_ats prune + 100-entry cap in
# phone_down.maybe_violation_penalty — same blob-growth discipline.
MAX_SPANS_PER_SESSION = 200
# Same bound for the dedupe-belt list itself — span and violation eids
# share it, so neither event type can inflate the blob without limit.
MAX_REPORTED_EVENT_IDS = 400
# Clock-skew slack lives in phone_down (the scan bound there needs it
# too, and service already imports the module) — see AT_TS_SKEW_SECONDS.


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


async def _session_for_phone_event(
    db: AsyncSession, user_id: int, event: GameEventIn
) -> FocusSession | None:
    """Resolve the session a phone_down_* event targets; None = unresolvable.

    Same trust rule as _habit_for_event: only an int id that maps to an
    owned row can mutate — a foreign/deleted/malformed session_id records
    unscored, never a 400 that would wedge the client's retry queue.
    """
    session_id = event.payload.get("session_id")
    if not isinstance(session_id, int) or isinstance(session_id, bool):
        return None
    return await game_crud.get_session(db, session_id, user_id)


def _dedupe_belt(blob: dict, eid: str) -> tuple[list, bool]:
    """(reported-eids list, already-applied) — the lost-ledger-row belt.

    uq_game_events already dedupes retries; this list additionally stops a
    marker eid re-applying when the ledger row was lost. Bounded at
    MAX_REPORTED_EVENT_IDS by _dedupe_belt_append.
    """
    reported = blob.get("reported_client_event_ids")
    reported = reported if isinstance(reported, list) else []
    return reported, eid in reported


def _dedupe_belt_append(reported: list, eid: str) -> list:
    """The belt + eid — past the cap the unique constraint alone dedupes
    retries, so a client can't grow the blob forever with marker eids."""
    if len(reported) >= MAX_REPORTED_EVENT_IDS:
        return list(reported)
    return [*reported, eid]


async def _apply_span_event(db: AsyncSession, session: FocusSession, event: GameEventIn) -> dict:
    """Validate + adjudicate one phone_down_span; appends to the blob.

    Returns the _outcome fields: {"applied": true, "tier": adjudicated} on
    success, {"reason": ...} on rejection. The blob is REASSIGNED (not
    mutated in place) — SQLAlchemy's plain-JSON column tracks assignment,
    not deep edits (the speedrun blob's _speedrun_result precedent).
    Adjudication is an ingest-time decision for the span's own claim; a
    LATER violation event still downgrades it (violations dominate).
    """
    p = event.payload
    claimed = p.get("claimed_tier")
    evidence = p.get("evidence")
    start = phone_down.parse_ts(p.get("start_ts"))
    end = phone_down.parse_ts(p.get("end_ts"))
    if claimed not in phone_down.TIERS:
        return {"reason": "invalid_claimed_tier"}
    if evidence not in phone_down.EVIDENCE_KINDS:
        return {"reason": "invalid_evidence"}
    if start is None or end is None or end <= start:
        return {"reason": "invalid_span"}
    # The window can't extend past receipt+skew: a span ending in the
    # future would capture violations reported later via re-adjudication.
    # (No matching start-floor: violation rows are session-scoped anyway,
    # so a pre-session span can absorb nothing extra.)
    if end > datetime.now(timezone.utc) + timedelta(seconds=phone_down.AT_TS_SKEW_SECONDS):
        return {"reason": "invalid_span"}
    blob = phone_down.blob_of(session)
    reported, already = _dedupe_belt(blob, event.client_event_id)
    if already:
        # Belt over uq_game_events: a span eid already applied to THIS
        # session can't append twice even if the ledger row was lost.
        return {"applied": True, "deduped": True}
    spans = blob.get("spans")
    spans = spans if isinstance(spans, list) else []
    if len(spans) >= MAX_SPANS_PER_SESSION:
        return {"reason": "span_cap_reached"}
    covered = await phone_down.violation_covers(db, session, start, end)
    tier = phone_down.adjudicate_tier(claimed, evidence, covered)
    assert tier is not None  # enums validated above
    span = {
        "start_ts": start.isoformat(),
        "end_ts": end.isoformat(),
        "tier": tier,
        "evidence": evidence,
    }
    session.phone_down = {
        **blob,
        "spans": [*spans, span],
        "reported_client_event_ids": _dedupe_belt_append(reported, event.client_event_id),
    }
    return {"applied": True, "tier": tier}


def _apply_violation_event(session: FocusSession, event: GameEventIn) -> dict:
    """Validate + count one phone_down_violation marker on the blob.

    Increments `violations` and re-adjudicates any already-stored spans
    whose window contains the instant (violations dominate regardless of
    upload order). HP cost is decided at phase scoring time (2nd+ inside
    the repeat window), so a first violation is warning-only and a late
    batch can't smuggle HP loss past the window.
    """
    p = event.payload
    kind = p.get("kind")
    at_ts = phone_down.parse_ts(p.get("at_ts"))
    if kind not in phone_down.VIOLATION_KINDS:
        return {"reason": "invalid_kind"}
    if at_ts is None:
        return {"reason": "invalid_at_ts"}
    # A violation can't precede itself: at_ts past the server's own
    # receipt instant (beyond clock skew) is malformed — and such rows
    # escape the server_ts>=since penalty-scan bound, so they must not
    # land. Bounds on server-now, not client_ts: a client may legitimately
    # backdate client_ts and the row must still adjudicate.
    if at_ts > datetime.now(timezone.utc) + timedelta(seconds=phone_down.AT_TS_SKEW_SECONDS):
        return {"reason": "future_at_ts"}
    blob = phone_down.blob_of(session)
    reported, already = _dedupe_belt(blob, event.client_event_id)
    if already:
        # Same belt as spans — a retried violation can't double-count.
        return {"applied": True, "deduped": True}
    try:
        violations = int(blob.get("violations") or 0)
    except (TypeError, ValueError):
        # Corrupt stored count: degrade to 0 — a poisoned blob must not
        # wedge the batch on a ValueError (all_verified's defensive read).
        violations = 0
    # A violation whose client_ts orders after its overlapping span still
    # re-adjudicates it — "violations dominate" is absolute, not ordered
    # by upload luck. Mirrors violation_covers' [start, end] bounds and
    # adjudicate_tier's any-tier downgrade (unverified included).
    spans = blob.get("spans")
    new_spans = (
        [
            (
                {**s, "tier": phone_down.VIOLATED}
                if (
                    isinstance(s, dict)
                    and s.get("tier") != phone_down.VIOLATED
                    and (st := phone_down.parse_ts(s.get("start_ts"))) is not None
                    and (et := phone_down.parse_ts(s.get("end_ts"))) is not None
                    and st <= at_ts <= et
                )
                else s
            )
            for s in spans
        ]
        if isinstance(spans, list)
        else spans
    )
    session.phone_down = {
        **blob,
        **({"spans": new_spans} if isinstance(new_spans, list) else {}),
        "violations": violations + 1,
        "reported_client_event_ids": _dedupe_belt_append(reported, event.client_event_id),
    }
    return {"applied": True}


async def _ingest_phone_down(
    db: AsyncSession,
    user_id: int,
    event: GameEventIn,
) -> None:
    """Apply one phone_down_span / phone_down_violation marker event.

    These events carry no score of their own — they mutate the session's
    phone_down blob (adjudicated span append / violation count) and record
    a ledger row whose _outcome says what happened. Rejections record
    applied-but-unscored like the habit/daily paths: one bad queued event
    must not 400 the batch, and its eid stays consumed (a corrected event
    must be resent under a NEW client_event_id).
    """
    session = await _session_for_phone_event(db, user_id, event)
    if session is None:
        result = {"reason": "session_unresolvable"}
    elif not phone_down.enabled(session):
        result = {"reason": "phone_down_not_enabled"}
    elif event.type == phone_down.SPAN_EVENT:
        result = await _apply_span_event(db, session, event)
    else:
        result = _apply_violation_event(session, event)
    applied = result.get("applied") is True
    outcome = {"scored": False, **result}
    db.add(
        GameEvent(
            user_id=user_id,
            client_event_id=event.client_event_id,
            type=event.type,
            payload={
                **habit_service.clean_extra(event.payload),
                # session_id is server-reserved in stored payloads — written
                # back only for applied rows, resolved server-side, so the
                # violation-window count and the feed can't be forged.
                **({"session_id": session.id} if applied and session is not None else {}),
                "_outcome": outcome,
            },
            client_ts=event.client_ts,
        )
    )
    # autoflush is disabled project-wide: a same-batch span re-reads applied
    # violation rows for window coverage (daily_service precedent).
    await db.flush()


async def _resolve_phone_down_payload(
    db: AsyncSession,
    user_id: int,
    event: GameEventIn,
    rates: GameRates,
) -> tuple[dict, FocusSession | None]:
    """(payload, session) for a synced focus_phase_completed.

    A client-supplied phone_down weight block never reaches the engine:
    when the event resolves to an owned phone-down session the block is
    recomputed server-side over [client_ts - minutes, client_ts]; anything
    else has the key stripped — a forged multiplier would otherwise
    self-award verified pay.
    """
    payload = event.payload
    session = await _session_for_phone_event(db, user_id, event)
    if session is not None and phone_down.enabled(session):
        minutes = payload.get("minutes")
        if (
            isinstance(minutes, (int, float))
            and not isinstance(minutes, bool)
            and 0 < minutes <= 1e6
        ):
            w_end = event.client_ts
            block = await phone_down.weight_block(
                db,
                session,
                w_start=w_end - timedelta(seconds=float(minutes) * 60),
                w_end=w_end,
                paid_minutes=float(minutes),
                rates=rates,
            )
            clean = {k: v for k, v in payload.items() if k != "phone_down"}
            return {**clean, "phone_down": block}, session
        # An unpayable minutes claim strips the block too — the engine's
        # own guard reports the shape downstream.
    return {k: v for k, v in payload.items() if k != "phone_down"}, session


async def _apply_generic(
    db: AsyncSession,
    user_id: int,
    event: GameEventIn,
    profile: GameProfile,
    rates: GameRates,
    today,
    rng: random.Random,
    stat_bonus: dict[str, int],
) -> tuple[dict, dict[str, int], dict, FocusSession | None]:
    """Score one generic (non-habit/non-daily) event.

    A ValueError from the engine's payload guards records applied-but-
    unscored like the habit/daily paths — one malformed queued event must
    not 400 the batch and wedge the client's retry queue forever. Returns
    (outcome, stat_bonus, payload, session) — the payload actually scored
    so the ledger stores the server-resolved phone_down block, not a
    client claim, and the resolved session so the stored row can carry
    the verified session_id (a client claim alone can't be trusted).
    """
    hp_before = profile.hp
    session: FocusSession | None = None
    payload = event.payload
    if event.type == "focus_phase_completed":
        payload, session = await _resolve_phone_down_payload(db, user_id, event, rates)
    try:
        outcome = engine.apply_event(
            profile,
            event.type,
            payload,
            rates,
            rng_roll=rng.random(),
            rng=rng,
            today=today,
            stat_bonus=stat_bonus,
        )
    except ValueError as exc:
        return {"scored": False, "reason": str(exc)}, stat_bonus, payload, session
    await character_service.resolve_death_gear(db, user_id, outcome, rng)
    await notifications.notify_score_outcome(db, user_id, profile, hp_before, outcome)
    if event.type == "focus_phase_completed" and outcome.get("scored"):
        await notifications.notify_phase_end(
            db, user_id, event.client_ts, event.payload.get("minutes")
        )
        if session is not None and phone_down.enabled(session):
            # Repeat-violation HP penalty — same scoring-call rule as the
            # server-side session path in session_service. The derived eid
            # hashes the client eid (unbounded length) like habit_service's
            # auto-click ids — truncating raw input could collide. Accepted:
            # a 64-bit eid collision makes the flush raise IntegrityError
            # and fails the batch rather than double-charging (birthday
            # bound needs ~2^32 events).
            penalty = await phone_down.maybe_violation_penalty(
                db,
                user_id,
                session,
                at=event.client_ts,
                profile=profile,
                rates=rates,
                stat_bonus=stat_bonus,
                rng=rng,
                eid=f"server:s{session.id}:phone_down_hp:sync:"
                f"{hashlib.sha1(event.client_event_id.encode(), usedforsecurity=False).hexdigest()[:16]}",
            )
            phone_down.merge_penalty(outcome, penalty)
    stat_bonus = await _refresh_bonus_on_gear_loss(db, user_id, outcome, stat_bonus)
    return outcome, stat_bonus, payload, session


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
    # Lock order: session rows BEFORE the profile FOR UPDATE. The session
    # verbs take theirs in that order (_locked_session → _evaluate's
    # profile lock), so an ingest doing profile→session is the classic
    # cross-direction deadlock on Postgres (40P01). The batch events that
    # can write a session row — the phone_down_* blob mutations, and a
    # synced focus_phase_completed whose repeat-violation penalty bumps
    # penalized_violation_ats — lock their targets up front. Unresolvable or
    # missing ids simply don't lock; the unscored-row path handles them.
    phone_session_ids = sorted(
        {
            e.payload["session_id"]
            for e in events
            if e.type
            in (phone_down.SPAN_EVENT, phone_down.VIOLATION_EVENT, "focus_phase_completed")
            and isinstance(e.payload.get("session_id"), int)
            and not isinstance(e.payload.get("session_id"), bool)
        }
    )
    # Ensure the profile row exists BEFORE locking: get_or_create_profile's
    # create-race recovery rolls back the transaction, which would release
    # the session locks taken below (READ COMMITTED — lost locks stay
    # lost). Unlocked here is safe: the create path is a no-op once the
    # row exists, and no work is pending to lose yet. The FOR UPDATE read
    # afterwards can never hit the create path, so the lock ordering above
    # is preserved.
    await game_crud.get_or_create_profile(db, user_id)
    await game_crud.lock_sessions(db, user_id, phone_session_ids)
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
        if event.type in (phone_down.SPAN_EVENT, phone_down.VIOLATION_EVENT):
            await _ingest_phone_down(db, user_id, event)
            _auto_distribute(profile)
            seen.add(event.client_event_id)
            status_by_idx[idx] = "applied"
            continue
        outcome, stat_bonus, resolved, session = await _apply_generic(
            db, user_id, event, profile, rates, today, rng, stat_bonus
        )
        # Engine outcome lands under "_outcome" so client payload keys never
        # collide with bookkeeping in the immutable ledger row. Client extras
        # are cleaned of server-reserved markers — a forged auto/session_id
        # can't masquerade a claimed event as server-authored metadata. The
        # RESOLVED session id is written back like _ingest_phone_down's
        # applied rows, so a synced focus phase stays attributable to its
        # session — unresolvable claims keep nothing.
        payload = {
            **habit_service.clean_extra(resolved),
            **({"session_id": session.id} if session is not None else {}),
            "_outcome": outcome,
        }
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
