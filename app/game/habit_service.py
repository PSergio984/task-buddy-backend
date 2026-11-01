"""Habit click orchestration: direction rules, drift write-back, ledger rows.

One scoring path for every click — the endpoint's synchronous click, an
offline-synced habit_click event, and the focus-binding auto-click. The
stored Habit.value (never a client-claimed one) drives drift; each click
writes back the new value, moves the net counter, and lands a habit_click
row in the event ledger so the timeline/catchup feed sees it.
"""

import hashlib
import random
from datetime import date, datetime
from typing import Any, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as game_crud
from app.game.engine import GameRates, apply_event
from app.models.game import GameEvent, GameProfile, Habit, HabitDirection

_rng = random.Random()


def check_direction(habit: Habit, direction: Any) -> Literal["positive", "negative"]:
    """Validate a click direction against the habit; return it narrowed."""
    if direction not in ("positive", "negative"):
        raise ValueError("habit_click requires direction 'positive' or 'negative'")
    if habit.direction is not HabitDirection.BOTH and habit.direction.value != direction:
        raise ValueError(f"habit does not accept {direction} clicks")
    return cast("Literal['positive', 'negative']", direction)


async def score_click(
    db: AsyncSession,
    habit: Habit,
    direction: str,
    profile: GameProfile,
    rates: GameRates,
    today: date,
    *,
    eid: str,
    client_ts: datetime,
    rng: random.Random | None = None,
    extra: dict | None = None,
) -> dict:
    """Apply one click through the engine; write back drift + counter; ledger row.

    The stored value is authoritative — the engine reads it, returns the
    drifted new_value, and both land in the ledger payload alongside
    "_outcome" (direction/difficulty likewise override any client extras).
    """
    rng = rng if rng is not None else _rng
    before = float(habit.value)
    outcome = apply_event(
        profile,
        "habit_click",
        {"direction": direction, "value": before, "difficulty": habit.difficulty},
        rates,
        rng_roll=rng.random(),
        rng=rng,
        today=today,
    )
    habit.counter += 1 if direction == "positive" else -1
    habit.value = float(outcome["new_value"])
    payload = {
        **(extra or {}),
        "habit_id": habit.id,
        "direction": direction,
        "difficulty": habit.difficulty,
        "value": before,
        "_outcome": outcome,
    }
    db.add(
        GameEvent(
            user_id=habit.user_id,
            client_event_id=eid,
            type="habit_click",
            client_ts=client_ts,
            payload=payload,
        )
    )
    return outcome


async def auto_click_bound(
    db: AsyncSession,
    user_id: int,
    profile: GameProfile,
    rates: GameRates,
    today: date,
    *,
    source_eid: str,
    client_ts: datetime,
    rng: random.Random | None = None,
    habits: list[Habit] | None = None,
    extra: dict | None = None,
) -> None:
    """One +click per focus-bound habit for a completed focus phase.

    The derived eid is deterministic per (habit, triggering event) — the
    trigger's own dedupe guards replays, and the reserved "server:" prefix
    keeps clients from squatting the id. A negative-only habit accepts no
    +click, so binding it is a stored no-op.
    """
    rng = rng if rng is not None else _rng
    candidates = habits if habits is not None else await game_crud.list_habits(db, user_id)
    digest = hashlib.sha1(source_eid.encode()).hexdigest()[:16]
    for habit in candidates:
        if not habit.bind_focus or habit.direction is HabitDirection.NEGATIVE:
            continue
        await score_click(
            db,
            habit,
            "positive",
            profile,
            rates,
            today,
            eid=f"server:habit:{habit.id}:focus:{digest}",
            client_ts=client_ts,
            rng=rng,
            extra={"auto": True, **(extra or {})},
        )
