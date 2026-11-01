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

# Per-user cap — bounds the per-phase auto-click fanout and the habit map
# ingest builds for a batch.
MAX_HABITS_PER_USER = 100

# Max auto-clicks one batch ingest or session evaluation may spend — bound
# habits x scored phase events would otherwise multiply into tens of
# thousands of writes inside a single profile-locked transaction.
# shortcut: spec says per-phase-per-bound-habit; a breach only triggers at
# abuse scale (a legit week-offline sync is ≈ <=300 clicks).
MAX_AUTO_CLICKS_PER_EVAL = 500

# Keys a client may not plant on a ledger row: server-set markers only.
# direction/difficulty/value/habit_id may stay in client extras — scored rows
# overwrite them with the authoritative fields anyway and unscored rows keep
# them as context for why the event failed to score.
_EXTRA_DENY = frozenset({"auto", "session_id"})

_rng = random.Random()


def clean_extra(extra: dict | None) -> dict:
    """Client extras minus server-reserved marker keys.

    Applied wherever an untrusted payload lands in a ledger row so a manual
    click can't forge auto-click/session metadata.
    """
    return {
        k: v for k, v in (extra or {}).items() if k not in _EXTRA_DENY and not k.startswith("_")
    }


def direction_allows(habit: Habit, direction: str) -> bool:
    """Whether the habit's direction accepts this click direction."""
    return habit.direction is HabitDirection.BOTH or habit.direction.value == direction


def check_direction(habit: Habit, direction: Any) -> Literal["positive", "negative"]:
    """Validate a click direction against the habit; return it narrowed."""
    if direction not in ("positive", "negative"):
        raise ValueError("habit_click requires direction 'positive' or 'negative'")
    if not direction_allows(habit, direction):
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
    server_extra: dict | None = None,
) -> dict:
    """Apply one click through the engine; write back drift + counter; ledger row.

    The stored value is authoritative — the engine reads it, returns the
    drifted new_value, and both land in the ledger payload alongside
    "_outcome" (direction/difficulty likewise override any client extras).
    Callers hold the user's profile lock; the flush+refresh reloads the habit
    against the latest committed state — including this transaction's own
    earlier writes — so back-to-back clicks in one batch drift sequentially
    and a concurrently committed row update can't be lost.
    """
    rng = rng if rng is not None else _rng
    await db.flush()
    await db.refresh(habit)
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
        **clean_extra(extra),
        **(server_extra or {}),
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
    server_extra: dict | None = None,
    budget: int | None = None,
) -> int:
    """One +click per focus-bound habit for a completed focus phase.

    The derived eid is deterministic per (habit, triggering event) — the
    trigger's own dedupe guards replays, and the reserved "server:" prefix
    keeps clients from squatting the id. A negative-only habit accepts no
    +click, so binding it is a stored no-op.

    `budget` caps this call's share of the caller's per-evaluation fanout
    (defaults to MAX_AUTO_CLICKS_PER_EVAL); returns the clicks spent so the
    caller can decrement its running total.

    Spec notes (resolve #44 says literally "per focus_phase_completed"):
    - stopwatch_milestone deliberately does NOT auto-click — milestones are
      not phase completions.
    - If a client-claimed phase event AND the server-side session engine
      both score the same phase (different eids), the union-merge dedupe
      can credit a bound habit twice. That's the accepted cross-path cost
      of the offline contract.
    """
    rng = rng if rng is not None else _rng
    candidates = habits if habits is not None else await game_crud.list_habits(db, user_id)
    limit = MAX_AUTO_CLICKS_PER_EVAL if budget is None else budget
    digest = hashlib.sha1(source_eid.encode(), usedforsecurity=False).hexdigest()[:16]
    spent = 0
    for habit in candidates:
        if spent >= limit:
            break
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
            server_extra={**(server_extra or {}), "auto": True},
        )
        spent += 1
    return spent
