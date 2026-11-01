"""Pure wall-clock state machine for focus sessions (no DB, no I/O).

The server anchors every transition to its own clock: an active focus phase
completes when its planned seconds elapse (scored), a break auto-starts and
auto-completes, and a pending phase left untapped past grace ends the session.
evaluate() mutates the session/phase rows to the correct end state and returns
the transition steps — the service persists the rows and writes the ledger
events for each step.

Abandon rules (spec #41): manual stop or absence-grace cost HP only with zero
completed focus phases (>=1 is a clean exit); pause-overflow is a violation
and always abandons.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.game import FocusPhase, FocusSession

GRACE_SECONDS = 300  # absence grace after a phase boundary (spec: break-end +5m)

PENDING, ACTIVE, PAUSED, COMPLETED, SKIPPED, ABANDONED = (
    "pending",
    "active",
    "paused",
    "completed",
    "skipped",
    "abandoned",
)
S_ACTIVE, S_ENDED, S_ABANDONED = "active", "ended", "abandoned"
FOCUS, BREAK, STOPWATCH = "focus", "break", "stopwatch"

MAX_MILESTONES = 100  # ~41 h of stopwatch; caps per-stop ledger rows


@dataclass
class Step:
    """One ledger-worthy transition produced by evaluate()."""

    kind: str  # phase_completed|phase_started|phase_paused|phase_resumed|
    #            phase_skipped|session_started|session_ended|session_abandoned
    phase_seq: int | None = None
    at: datetime | None = None
    actual_seconds: int | None = None
    scored: bool = False
    reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _live(phases: list[FocusPhase]) -> FocusPhase | None:
    return next((p for p in phases if p.status in (ACTIVE, PAUSED)), None)


def _next_pending(phases: list[FocusPhase]) -> FocusPhase | None:
    return next((p for p in phases if p.status == PENDING), None)


def completed_focus_count(phases: list[FocusPhase]) -> int:
    return sum(1 for p in phases if p.kind == FOCUS and p.status == COMPLETED)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite returns naive datetimes; all arithmetic assumes UTC-aware.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _phase_end(phase: FocusPhase, now: datetime) -> datetime:
    # Only live phases reach here; started_at is always set for them.
    start = _aware(phase.started_at) or now
    return start + timedelta(seconds=phase.planned_seconds + (phase.paused_seconds or 0))


def _resolve_no_live(
    session: FocusSession, phases: list[FocusPhase], last_end: datetime, now: datetime
) -> Step | None:
    """Nothing running: end when the plan is done, else grace-watch the
    pending phase (absent past break-end + grace -> clean end / abandon)."""
    if _next_pending(phases) is None:
        session.status = S_ENDED
        session.ended_at = last_end
        return Step("session_ended", at=last_end)
    anchor = last_end
    if now < anchor + timedelta(seconds=GRACE_SECONDS):
        return None  # still inside the grace window
    at = anchor + timedelta(seconds=GRACE_SECONDS)
    if completed_focus_count(phases) == 0:
        session.status = S_ABANDONED
        session.ended_at = at
        return Step("session_abandoned", reason="absence_grace", at=at)
    session.status = S_ENDED
    session.ended_at = at
    return Step("session_ended", at=at)


def _check_pause_overflow(session: FocusSession, cur: FocusPhase, now: datetime) -> Step | None:
    """A paused non-stopwatch phase over its seconds budget abandons."""
    banked = cur.paused_seconds or 0
    pause_start = _aware(cur.pause_started_at) or now
    extra = int((now - pause_start).total_seconds())
    if banked + extra <= session.pause_budget_seconds:
        return None
    crossed_at = pause_start + timedelta(seconds=session.pause_budget_seconds - banked)
    session.status = S_ABANDONED
    session.ended_at = crossed_at
    cur.status = ABANDONED
    cur.ended_at = crossed_at
    cur.paused_seconds = banked + extra  # bank the final pause before clearing
    cur.pause_started_at = None
    return Step("session_abandoned", reason="pause_overflow", phase_seq=cur.seq, at=crossed_at)


def _complete_phase(
    phases: list[FocusPhase],
    cur: FocusPhase,
    end: datetime,
    auto_breaks: bool,
    auto_focus: bool,
    steps: list[Step],
) -> None:
    """Mark the elapsed phase done and auto-start the next per toggles; a
    pending next phase is left for the grace watch on the following pass."""
    steps.append(
        Step(
            "phase_completed",
            phase_seq=cur.seq,
            at=end,
            actual_seconds=cur.planned_seconds,
            scored=cur.kind == FOCUS,
        )
    )
    cur.status = COMPLETED
    cur.actual_seconds = cur.planned_seconds
    cur.ended_at = end
    nxt = _next_pending(phases)
    if nxt is not None and (auto_breaks if nxt.kind == BREAK else auto_focus):
        nxt.status = ACTIVE
        nxt.started_at = end
        steps.append(Step("phase_started", phase_seq=nxt.seq, at=end))


def evaluate(session: FocusSession, phases: list[FocusPhase], now: datetime) -> list[Step]:
    """Replay elapsed wall-clock transitions; mutates session+phases in place.

    Caller must hold the session row lock (FOR UPDATE) — two evaluations on
    stale snapshots would double-emit steps.
    """
    if session.status != S_ACTIVE:
        return []
    preset = session.preset or {}
    auto_focus = bool(preset.get("auto_start_focus", False))
    auto_breaks = bool(preset.get("auto_start_breaks", True))
    steps: list[Step] = []
    # Grace/timeline anchor: newest finished phase; the session start before
    # any completion. Must survive across calls — started_at alone would make
    # every pending-phase session older than GRACE_SECONDS end on the next poll.
    ended = [e for p in phases if (e := _aware(p.ended_at)) is not None]
    last_end = max(ended, default=_aware(session.started_at) or now)

    while True:
        cur = _live(phases)
        if cur is None:
            step = _resolve_no_live(session, phases, last_end, now)
            if step is not None:
                steps.append(step)
            return steps
        if cur.kind == STOPWATCH:
            return steps  # open-ended; a paused stopwatch just sits
        if cur.status == PAUSED:
            step = _check_pause_overflow(session, cur, now)
            if step is not None:
                steps.append(step)
            return steps
        # cur is ACTIVE: complete it when its planned window elapsed.
        end = _phase_end(cur, now)
        if now < end:
            return steps
        _complete_phase(phases, cur, end, auto_breaks, auto_focus, steps)
        last_end = end


def pause(session: FocusSession, phase: FocusPhase | None, now: datetime) -> Step:
    """Validate + apply a pause on the live phase; returns a phase_paused Step,
    or a session_abandoned Step when the count budget is exceeded."""
    if phase is None or phase.status != ACTIVE:
        raise ValueError("no running phase to pause")
    if phase.kind == BREAK:
        raise ValueError("breaks cannot be paused")
    if phase.kind == STOPWATCH or (phase.pause_count or 0) + 1 <= session.pause_budget_count:
        # Stopwatch pauses bank time but carry no budget.
        phase.pause_count = (phase.pause_count or 0) + 1
        phase.pause_started_at = now
        phase.status = PAUSED
        # n disambiguates rapid pause->resume->pause cycles inside one second,
        # which would otherwise collide on identical server event ids.
        return Step("phase_paused", phase_seq=phase.seq, at=now, extra={"n": phase.pause_count})
    phase.status = ABANDONED
    phase.ended_at = now
    phase.pause_started_at = None
    session.status = S_ABANDONED
    session.ended_at = now
    return Step("session_abandoned", reason="pause_overflow", phase_seq=phase.seq, at=now)


def resume(session: FocusSession, phase: FocusPhase | None, now: datetime) -> Step:
    """Validate + apply a resume; banks paused seconds and returns an abandon
    Step when the seconds budget was already blown."""
    if phase is None or phase.status != PAUSED:
        raise ValueError("no paused phase to resume")
    extra = int((now - (_aware(phase.pause_started_at) or now)).total_seconds())
    if phase.kind == FOCUS and (phase.paused_seconds or 0) + extra > session.pause_budget_seconds:
        phase.status = ABANDONED
        phase.ended_at = now
        phase.paused_seconds = (phase.paused_seconds or 0) + extra
        phase.pause_started_at = None
        session.status = S_ABANDONED
        session.ended_at = now
        return Step("session_abandoned", reason="pause_overflow", phase_seq=phase.seq, at=now)
    phase.paused_seconds = (phase.paused_seconds or 0) + extra
    phase.pause_started_at = None
    phase.status = ACTIVE
    return Step("phase_resumed", phase_seq=phase.seq, at=now, extra={"n": phase.pause_count})


def advance(session: FocusSession, phases: list[FocusPhase], now: datetime) -> list[Step]:
    """User tap: begin the pending focus phase, or skip a running break."""
    live = _live(phases)
    if live is not None and live.kind == BREAK and live.status == ACTIVE:
        live.status = SKIPPED
        live.ended_at = now
        skip = Step("phase_skipped", phase_seq=live.seq, at=now)
        pend = _next_pending(phases)
        if pend is not None:
            pend.status = ACTIVE
            pend.started_at = now
            return [skip, Step("phase_started", phase_seq=pend.seq, at=now)]
        session.status = S_ENDED
        session.ended_at = now
        return [skip, Step("session_ended", at=now)]
    if live is not None:
        raise ValueError("a phase is still running")
    pend = _next_pending(phases)
    if pend is None:
        raise ValueError("no pending phase")
    pend.status = ACTIVE
    pend.started_at = now
    return [Step("phase_started", phase_seq=pend.seq, at=now)]


def stop(session: FocusSession, phases: list[FocusPhase], now: datetime) -> tuple[Step, list[Step]]:
    """End the session now. Returns (final_step, scored_steps) — a stopwatch
    stop may emit milestone steps before the end step."""
    scored: list[Step] = []
    live = _live(phases)
    if live is not None and live.kind == STOPWATCH:
        started = _aware(live.started_at) or now
        elapsed = int((now - started).total_seconds())
        paused = live.paused_seconds or 0
        if live.status == PAUSED:
            # Bank the open pause too — else it counts as focus time.
            paused += int((now - (_aware(live.pause_started_at) or now)).total_seconds())
        actual = max(0, elapsed - paused)
        live.actual_seconds = actual
        live.paused_seconds = paused
        live.pause_started_at = None
        live.status = COMPLETED
        live.ended_at = now
        bound = min(actual // 60, MAX_MILESTONES * 25)
        for i, minutes in enumerate(range(25, bound + 1, 25), start=1):
            # shortcut: crossing ts assumes all pauses preceded the milestone —
            # exact reconstruction needs per-pause intervals we don't store.
            crossed = started + timedelta(seconds=minutes * 60 + paused)
            scored.append(
                Step(
                    "phase_completed",
                    phase_seq=live.seq,
                    at=crossed,
                    actual_seconds=minutes * 60,
                    scored=True,
                    extra={"milestone_index": i},
                )
            )
    else:
        if live is not None:
            if live.status == PAUSED and live.pause_started_at is not None:
                live.paused_seconds = (live.paused_seconds or 0) + int(
                    (now - (_aware(live.pause_started_at) or now)).total_seconds()
                )
                live.pause_started_at = None
            live.status = ABANDONED if live.kind == FOCUS else SKIPPED
            live.ended_at = now
            # The feed needs the phase transition too — session_ended alone
            # can't say what happened to the phase that was live.
            scored.append(
                Step(
                    "phase_abandoned" if live.status == ABANDONED else "phase_skipped",
                    phase_seq=live.seq,
                    at=now,
                )
            )
        # Stopping with nothing scored is an abandon regardless of which phase
        # was live (or none) — a clean end requires >=1 completed focus.
        if completed_focus_count(phases) == 0:
            session.status = S_ABANDONED
            session.ended_at = now
            return (
                Step(
                    "session_abandoned",
                    reason="manual_stop",
                    phase_seq=live.seq if live is not None else None,
                    at=now,
                ),
                scored,
            )
    session.status = S_ENDED
    session.ended_at = now
    return Step("session_ended", at=now), scored
