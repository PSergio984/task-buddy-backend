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
from app.game import engine
from app.game.engine import GameRates
from app.models.game import GameEvent, GameProfile
from app.schemas.game import GameEventIn, GameEventResult

_rng = random.Random()


async def load_rates(db: AsyncSession) -> GameRates:
    config_map = await game_crud.get_config_map(db)
    return GameRates.from_dict(config_map.get("economy", {}))


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
    for idx, event in ordered:
        if event.client_event_id in seen:
            status_by_idx[idx] = "duplicate"
            continue
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
        seen.add(event.client_event_id)
        status_by_idx[idx] = "applied"
    await db.flush()
    results = [
        GameEventResult(client_event_id=e.client_event_id, status=status_by_idx[i])
        for i, e in enumerate(events)
    ]
    return profile, results, rates
