"""Focus-session orchestration: state machine + ledger + scoring.

Every lifecycle call (start / pause / resume / advance / stop / read) first
replays elapsed wall-clock transitions via session_engine.evaluate(), then
applies the requested verb, then persists everything in one transaction —
the caller's router commits. Scored steps go through the game engine so
totals, crits and the death cascade behave identically to /events ingestion.
"""

import random
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as game_crud
from app.game import session_engine as se
from app.game.engine import GameRates, apply_event
from app.game.service import load_rates
from app.models.game import FocusPhase, FocusSession, GameEvent, GameProfile
from app.models.tag import Tag
from app.models.task import Task
from app.schemas.game import SessionStartIn

_rng = random.Random()


class ConflictError(Exception):
    """409 — request collides with current state (e.g. session already active)."""


class NotFoundError(Exception):
    """404 — the referenced resource does not exist (or is not the caller's)."""


def _event_id(session_id: int, kind: str, seq: int | None, at: datetime, i: int) -> str:
    return f"server:s{session_id}:{kind}:{seq or 0}:{int(at.timestamp())}:{i}"


def _event_for(step: se.Step, session: FocusSession) -> tuple[str | None, dict]:
    """Map one transition step to its ledger (type, payload); None = skip."""
    preset = session.preset or {}
    difficulty = preset.get("difficulty", "easy")
    payload: dict = {"session_id": session.id}
    kind = step.kind
    if kind == "phase_completed" and step.scored:
        if step.extra.get("milestone_index"):
            return "stopwatch_milestone", {
                **payload,
                "milestones": 1,
                "milestone_index": step.extra["milestone_index"],
                "phase_seq": step.phase_seq,
            }
        return "focus_phase_completed", {
            **payload,
            "minutes": max(1, (step.actual_seconds or 0) // 60),
            "difficulty": difficulty,
            "phase_seq": step.phase_seq,
        }
    if kind == "phase_completed":
        # Unscored completions (breaks) still land in the ledger so the feed
        # reconstructs the whole session, not just scored transitions.
        return kind, {**payload, "phase_seq": step.phase_seq}
    if kind == "session_started":
        return kind, {
            **payload,
            **step.extra,
            "task_id": session.task_id,
            "difficulty": difficulty,
        }
    if kind == "session_abandoned":
        return kind, {
            **payload,
            "reason": step.reason,
            "difficulty": difficulty,
            "phase_seq": step.phase_seq,
        }
    if kind in ("phase_started", "phase_paused", "phase_resumed", "phase_skipped"):
        return kind, {**payload, "phase_seq": step.phase_seq}
    if kind == "session_ended":
        return kind, payload
    return None, payload


async def _persist_step(
    db: AsyncSession,
    session: FocusSession,
    user_id: int,
    step: se.Step,
    i: int,
    profile: GameProfile | None,
    rates: GameRates,
    now: datetime,
    seen: set[str],
) -> None:
    """Write one transition's ledger row; score it when the engine knows how.

    `now` is the caller's evaluation instant — the same fallback used to build
    the dedupe id set, so a Step without `at` dedupes correctly on retry.
    """
    event_type, payload = _event_for(step, session)
    if event_type is None:
        return
    at = step.at or now
    eid = _event_id(session.id, step.kind, step.phase_seq, at, step.extra.get("n", i))
    if eid in seen:
        return
    seen.add(eid)
    outcome = {"scored": False}
    if profile is not None and event_type in (
        "focus_phase_completed",
        "stopwatch_milestone",
        "session_abandoned",
    ):
        outcome = apply_event(profile, event_type, payload, rates, _rng.random(), _rng, now.date())
    row = GameEvent(
        user_id=user_id,
        client_event_id=eid,
        type=event_type,
        client_ts=at,
        payload={**payload, "_outcome": outcome},
    )
    db.add(row)


async def _evaluate(
    db: AsyncSession,
    session: FocusSession,
    user_id: int,
    now: datetime,
    need_steps: list[se.Step] | None = None,
) -> tuple[list[FocusPhase], list[se.Step]]:
    """Replay elapsed transitions, persist their ledger rows, return state.

    Caller guarantees the profile row already exists (prefetched at txn start —
    get_or_create_profile's create-race rollback is only safe before any work
    is pending) and holds the session row lock.
    """
    phases = await game_crud.get_phases(db, session.id)
    steps = se.evaluate(session, phases, now)
    if need_steps:
        steps.extend(need_steps)
    if not steps:
        return phases, steps
    rates = await load_rates(db)
    scored = any(s.scored or s.kind == "session_abandoned" for s in steps)
    profile = (
        await game_crud.get_or_create_profile(db, user_id, for_update=True) if scored else None
    )
    if profile is not None:
        # The prefetch loaded this object before the FOR UPDATE — refresh so
        # scoring applies to the values committed under the lock, not a stale
        # snapshot a concurrent /events award may have already overwritten.
        await db.refresh(profile)
    ids = [  # deterministic ids; dedupe guards a retried evaluation
        _event_id(session.id, s.kind, s.phase_seq, s.at or now, s.extra.get("n", i))
        for i, s in enumerate(steps)
    ]
    seen = await game_crud.existing_event_ids(db, user_id, ids)
    for i, step in enumerate(steps):
        await _persist_step(db, session, user_id, step, i, profile, rates, now, seen)
    await db.flush()
    return phases, steps


def _plan(req: SessionStartIn) -> list[tuple[str, int]]:
    """Phase plan before any DB work — a bad request can't churn a rollback."""
    if req.mode == "stopwatch":
        return [("stopwatch", 0)]
    if not req.phases:
        raise ValueError("phases are required for timer mode")
    if not any(p.kind == "focus" for p in req.phases):
        raise ValueError("a plan needs at least one focus phase")
    return [(p.kind, p.minutes * 60) for p in req.phases]


async def _check_links(db: AsyncSession, user_id: int, req: SessionStartIn) -> None:
    """Linked task/tag must exist and belong to the caller."""
    if req.task_id is not None:
        task = await db.get(Task, req.task_id)
        if task is None or task.user_id != user_id:
            raise NotFoundError("task not found")
    if req.tag_id is not None:
        tag = await db.get(Tag, req.tag_id)
        if tag is None or tag.user_id != user_id:
            raise NotFoundError("tag not found")


async def start_session(
    db: AsyncSession, user_id: int, req: SessionStartIn
) -> tuple[FocusSession, list[FocusPhase], GameProfile]:
    plan = _plan(req)
    await _check_links(db, user_id, req)
    now = datetime.now(timezone.utc)
    # Profile before any pending work — the create-race rollback is only safe
    # at the start of a transaction.
    profile = await game_crud.get_or_create_profile(db, user_id)
    # A stale 'active' row may be clock-dead — evaluate it before conflicting.
    existing = await game_crud.get_active_session(db, user_id, for_update=True)
    if existing is not None:
        await _evaluate(db, existing, user_id, now)
        if existing.status == se.S_ACTIVE:
            raise ConflictError("an active session already exists")
    preset: dict = {
        "difficulty": req.difficulty,
        "auto_start_breaks": req.auto_start_breaks,
        "auto_start_focus": req.auto_start_focus,
    }
    if req.tag_id is not None:
        preset["tag_id"] = req.tag_id
    session = FocusSession(
        user_id=user_id,
        task_id=req.task_id,
        mode=req.mode,
        status="active",
        activity_label=req.activity_label,
        preset=preset,
        pause_budget_count=req.pause_budget_count,
        pause_budget_seconds=req.pause_budget_seconds,
        started_at=now,
    )
    db.add(session)
    try:
        await db.flush()  # uq_focus_sessions_one_active race -> IntegrityError
    except IntegrityError as exc:
        await db.rollback()
        detail = str(exc.orig)
        # SQLite reports index violations by table.column ("tbl_focus_sessions.user_id"),
        # Postgres by constraint name ("uq_focus_sessions_one_active").
        is_unique = "unique" in detail.lower()
        if not (is_unique and "focus_sessions" in detail):
            raise  # FK/CK violations aren't the one-active conflict
        raise ConflictError("an active session already exists") from exc
    phases = [
        FocusPhase(
            session_id=session.id,
            seq=i,
            kind=kind,
            status="active" if i == 0 else "pending",
            planned_seconds=secs,
            started_at=now if i == 0 else None,
        )
        for i, (kind, secs) in enumerate(plan)
    ]
    db.add_all(phases)
    await db.flush()
    await _persist_step(
        db,
        session,
        user_id,
        se.Step("session_started", at=now, extra={"mode": req.mode}),
        0,
        None,
        GameRates(),
        now,
        set(),
    )
    await _persist_step(
        db,
        session,
        user_id,
        se.Step("phase_started", phase_seq=0, at=now),
        1,
        None,
        GameRates(),
        now,
        set(),
    )
    return session, phases, profile


async def _locked_session(db: AsyncSession, user_id: int, session_id: int) -> FocusSession:
    session = await game_crud.get_session(db, session_id, user_id, for_update=True)
    if session is None:
        raise NotFoundError("session not found")
    return session


_View = tuple[FocusSession, list[FocusPhase], GameProfile]


async def get_view(db: AsyncSession, user_id: int, session_id: int) -> _View:
    profile = await game_crud.get_or_create_profile(db, user_id)
    session = await _locked_session(db, user_id, session_id)
    phases, _ = await _evaluate(db, session, user_id, datetime.now(timezone.utc))
    return session, phases, profile


async def get_active_view(db: AsyncSession, user_id: int) -> _View | None:
    # Cheap existence check first: prefetching the profile unconditionally
    # would write-then-rollback a new profile row on every /active poll.
    if await game_crud.get_active_session(db, user_id) is None:
        return None
    profile = await game_crud.get_or_create_profile(db, user_id)
    session = await game_crud.get_active_session(db, user_id, for_update=True)
    assert session is not None  # it existed a line ago and only we can end it
    phases, _ = await _evaluate(db, session, user_id, datetime.now(timezone.utc))
    return session, phases, profile


async def _action(
    db: AsyncSession,
    user_id: int,
    session_id: int,
    verb,
) -> _View:
    """evaluate → apply verb → persist — one locked transaction."""
    now = datetime.now(timezone.utc)
    profile = await game_crud.get_or_create_profile(db, user_id)
    session = await _locked_session(db, user_id, session_id)
    if session.status != se.S_ACTIVE:
        raise ConflictError("session is not active")
    phases, _ = await _evaluate(db, session, user_id, now)
    if session.status != se.S_ACTIVE:
        # The clock ended it before the verb landed — return the final state
        # rather than erroring (the transition is real and must persist).
        return session, phases, profile
    extra = verb(session, phases, now)
    if extra:
        await _evaluate(db, session, user_id, now, need_steps=extra)
    return session, phases, profile


async def pause(db: AsyncSession, user_id: int, session_id: int) -> _View:
    def verb(session: FocusSession, phases: list[FocusPhase], now: datetime) -> list[se.Step]:
        return [se.pause(session, se._live(phases), now)]

    return await _action(db, user_id, session_id, verb)


async def resume(db: AsyncSession, user_id: int, session_id: int) -> _View:
    def verb(session: FocusSession, phases: list[FocusPhase], now: datetime) -> list[se.Step]:
        return [se.resume(session, se._live(phases), now)]

    return await _action(db, user_id, session_id, verb)


async def advance(db: AsyncSession, user_id: int, session_id: int) -> _View:
    def verb(session: FocusSession, phases: list[FocusPhase], now: datetime) -> list[se.Step]:
        return se.advance(session, phases, now)

    return await _action(db, user_id, session_id, verb)


async def stop(db: AsyncSession, user_id: int, session_id: int) -> _View:
    def verb(session: FocusSession, phases: list[FocusPhase], now: datetime) -> list[se.Step]:
        final, scored = se.stop(session, phases, now)
        return scored + [final]

    return await _action(db, user_id, session_id, verb)
