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
from app.game import engine, habit_service
from app.game.engine import GameRates
from app.models.game import GameEvent, GameProfile, Habit
from app.schemas.game import GameEventIn, GameEventResult

_rng = random.Random()


async def load_rates(db: AsyncSession) -> GameRates:
    config_map = await game_crud.get_config_map(db)
    return GameRates.from_dict(config_map.get("economy", {}))


def _habit_for_event(event: GameEventIn, habits_by_id: dict[int, Habit]) -> Habit | None:
    """Resolve the habit a client habit_click targets; None = unresolvable.

    Only an int habit_id maps to a row — bool is excluded (True == 1 would
    silently resolve habit 1) and malformed ids get the same treatment as a
    deleted habit: the generic client-claimed-value path.
    """
    habit_id = event.payload.get("habit_id")
    if isinstance(habit_id, int) and not isinstance(habit_id, bool):
        return habits_by_id.get(habit_id)
    return None


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
    bound_habits = [h for h in habits_by_id.values() if h.bind_focus]
    for idx, event in ordered:
        if event.client_event_id in seen:
            status_by_idx[idx] = "duplicate"
            continue
        if event.type == "habit_click":
            habit = _habit_for_event(event, habits_by_id)
            if habit is not None:
                direction = habit_service.check_direction(habit, event.payload.get("direction"))
                await habit_service.score_click(
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
                )
                seen.add(event.client_event_id)
                status_by_idx[idx] = "applied"
                continue
            # Unresolvable habit_id (deleted/foreign/malformed): the generic
            # path scores the client-claimed value — the pre-#62 contract.
        outcome = engine.apply_event(
            profile, event.type, event.payload, rates, rng_roll=rng.random(), rng=rng, today=today
        )
        # Engine outcome lands under "_outcome" so client payload keys never
        # collide with bookkeeping in the immutable ledger row.
        payload = {**event.payload, "_outcome": outcome}
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
            await habit_service.auto_click_bound(
                db,
                user_id,
                profile,
                rates,
                today,
                source_eid=event.client_event_id,
                client_ts=event.client_ts,
                rng=rng,
                habits=bound_habits,
            )
        seen.add(event.client_event_id)
        status_by_idx[idx] = "applied"
    await db.flush()
    results = [
        GameEventResult(client_event_id=e.client_event_id, status=status_by_idx[i])
        for i, e in enumerate(events)
    ]
    return profile, results, rates
