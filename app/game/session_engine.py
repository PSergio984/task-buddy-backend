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

Speedrun (#69): a single open phase of kind 'speedrun'. time_boxed runs die
on their wall-clock deadline (pauses never extend it); beat_best is
open-ended like a stopwatch. A live speedrun phase never takes the
session_abandoned path — timeout/abandon emit speedrun_failed, and done()
is the user-declared win.
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
FOCUS, BREAK, STOPWATCH, SPEEDRUN = "focus", "break", "stopwatch", "speedrun"

MAX_MILESTONES = 100  # ~41 h of stopwatch; caps per-stop ledger rows

# Credit-eligibility floor: sub-minute completions still finish and earn
# duration XP, but can't hold a label's beat_best board or claim the win
# bonus — a speedrun under a minute isn't a serious recurring-activity
# attempt (anti-misclick + anti-trivial-cheat + anti bonus-farm).
MIN_RECORD_SECONDS = 60


@dataclass
class Step:
    """One ledger-worthy transition produced by evaluate()."""

    kind: str  # phase_completed|phase_started|phase_paused|phase_resumed|
    #            phase_skipped|session_started|session_ended|session_abandoned
    #            speedrun_completed|speedrun_failed|record_set
    phase_seq: int | None = None
    at: datetime | None = None
    actual_seconds: int | None = None
    scored: bool = False
    reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def live_phase(phases: list[FocusPhase]) -> FocusPhase | None:
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


def _skip_pending(phases: list[FocusPhase], at: datetime) -> list[Step]:
    """Close never-started phases on a dead session; one skip Step each.

    A phase left 'pending' on an ended/abandoned session reads as still
    startable to every reader — skip steps keep the ledger honest.
    """
    steps = []
    for phase in phases:
        if phase.status == PENDING:
            phase.status = SKIPPED
            phase.ended_at = at
            steps.append(Step("phase_skipped", phase_seq=phase.seq, at=at))
    return steps


def _resolve_no_live(
    session: FocusSession, phases: list[FocusPhase], last_end: datetime, now: datetime
) -> list[Step]:
    """Nothing running: end when the plan is done, else grace-watch the
    pending phase (absent past break-end + grace -> clean end / abandon)."""
    if _next_pending(phases) is None:
        session.status = S_ENDED
        session.ended_at = last_end
        return [Step("session_ended", at=last_end)]
    anchor = last_end
    if now < anchor + timedelta(seconds=GRACE_SECONDS):
        return []  # still inside the grace window
    at = anchor + timedelta(seconds=GRACE_SECONDS)
    skipped = _skip_pending(phases, at)
    if completed_focus_count(phases) == 0:
        session.status = S_ABANDONED
        session.ended_at = at
        return skipped + [Step("session_abandoned", reason="absence_grace", at=at)]
    session.status = S_ENDED
    session.ended_at = at
    return skipped + [Step("session_ended", at=at)]


def _check_pause_overflow(
    session: FocusSession, cur: FocusPhase, phases: list[FocusPhase], now: datetime
) -> list[Step]:
    """A paused non-stopwatch phase over its seconds budget abandons."""
    banked = cur.paused_seconds or 0
    pause_start = _aware(cur.pause_started_at) or now
    extra = int((now - pause_start).total_seconds())
    if banked + extra <= session.pause_budget_seconds:
        return []
    crossed_at = pause_start + timedelta(seconds=session.pause_budget_seconds - banked)
    session.status = S_ABANDONED
    session.ended_at = crossed_at
    cur.status = ABANDONED
    cur.ended_at = crossed_at
    cur.paused_seconds = banked + extra  # bank the final pause before clearing
    cur.pause_started_at = None
    # Never-started phases die with the session — same closeout as
    # _resolve_no_live, else they dangle 'pending' on a dead session.
    skipped = _skip_pending(phases, crossed_at)
    return skipped + [
        Step("session_abandoned", reason="pause_overflow", phase_seq=cur.seq, at=crossed_at)
    ]


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


def speedrun_type(session: FocusSession, phase: FocusPhase) -> str:
    """The run variant: the start-time blob is authoritative, planned_seconds
    is the fallback (budget>0 means a countdown)."""
    blob = session.speedrun if isinstance(session.speedrun, dict) else {}
    stype = str(blob.get("type"))
    if stype in ("time_boxed", "beat_best"):
        return stype
    return "time_boxed" if phase.planned_seconds > 0 else "beat_best"


def _speedrun_result(session: FocusSession, result: str, elapsed: int, **extra: Any) -> None:
    """Write the run's outcome into the speedrun blob (reassign — in-place
    mutation escapes SQLAlchemy's JSON change tracking). `extra` merges the
    decision-time facts the end screen needs (margin, old record, reason)
    but which otherwise only lived on the event payload."""
    blob = session.speedrun if isinstance(session.speedrun, dict) else {}
    session.speedrun = {**blob, "result": result, "elapsed_seconds": elapsed, **extra}


def _check_speedrun_deadline(
    session: FocusSession, cur: FocusPhase, phases: list[FocusPhase], now: datetime
) -> list[Step] | None:
    """Time-boxed miss: the countdown is wall-clock — pauses never extend
    it. Returns the transition steps when the deadline passed, else None."""
    if speedrun_type(session, cur) != "time_boxed":
        return None  # beat_best is open-ended; it just sits, paused or not
    started = _aware(cur.started_at) or now
    deadline = started + timedelta(seconds=cur.planned_seconds)
    if now < deadline:
        return None
    # Bank the open pause to the deadline — the phase ended there, not at
    # this (possibly late) evaluation. The countdown died anyway, but the
    # pause bookkeeping stays honest for the session record.
    _bank_open_pause(cur, deadline)
    cur.status = ABANDONED
    cur.ended_at = deadline
    session.status = S_ABANDONED
    session.ended_at = deadline
    _speedrun_result(session, "miss", cur.planned_seconds, reason="timeout")
    skipped = _skip_pending(phases, deadline)
    return skipped + [
        Step("phase_abandoned", phase_seq=cur.seq, at=deadline),
        Step(
            "speedrun_failed",
            phase_seq=cur.seq,
            at=deadline,
            scored=True,
            reason="timeout",
            extra={
                "speedrun_type": "time_boxed",
                "elapsed_seconds": cur.planned_seconds,
            },
        ),
    ]


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
        cur = live_phase(phases)
        if cur is None:
            steps.extend(_resolve_no_live(session, phases, last_end, now))
            return steps
        if cur.kind == STOPWATCH:
            return steps  # open-ended; a paused stopwatch just sits
        if cur.kind == SPEEDRUN:
            # Checked before the pause branch: a paused time-boxed run still
            # dies on deadline — pauses bank honesty data, never extra time.
            failed = _check_speedrun_deadline(session, cur, phases, now)
            if failed is not None:
                steps.extend(failed)
            return steps
        if cur.status == PAUSED:
            steps.extend(_check_pause_overflow(session, cur, phases, now))
            return steps
        # cur is ACTIVE: complete it when its planned window elapsed.
        end = _phase_end(cur, now)
        if now < end:
            return steps
        _complete_phase(phases, cur, end, auto_breaks, auto_focus, steps)
        last_end = end


def pause(session: FocusSession, phases: list[FocusPhase], now: datetime) -> list[Step]:
    """Validate + apply a pause on the live phase; returns the pause Step,
    or skip Steps + a session_abandoned Step when the count budget is
    exceeded (a dead session can't leave pending phases startable-looking)."""
    phase = live_phase(phases)
    if phase is None or phase.status != ACTIVE:
        raise ValueError("no running phase to pause")
    if phase.kind == BREAK:
        raise ValueError("breaks cannot be paused")
    if (
        phase.kind in (STOPWATCH, SPEEDRUN)
        or (phase.pause_count or 0) + 1 <= session.pause_budget_count
    ):
        # Stopwatch/speedrun pauses bank time but carry no budget (a
        # speedrun's countdown keeps ticking anyway — pausing buys nothing).
        phase.pause_count = (phase.pause_count or 0) + 1
        phase.pause_started_at = now
        phase.status = PAUSED
        # n disambiguates rapid pause->resume->pause cycles inside one second,
        # which would otherwise collide on identical server event ids.
        return [Step("phase_paused", phase_seq=phase.seq, at=now, extra={"n": phase.pause_count})]
    phase.status = ABANDONED
    phase.ended_at = now
    phase.pause_started_at = None
    session.status = S_ABANDONED
    session.ended_at = now
    return _skip_pending(phases, now) + [
        Step("session_abandoned", reason="pause_overflow", phase_seq=phase.seq, at=now)
    ]


def resume(session: FocusSession, phases: list[FocusPhase], now: datetime) -> list[Step]:
    """Validate + apply a resume; banks paused seconds and returns the resume
    Step, or skip Steps + a session_abandoned Step when the seconds budget
    was already blown."""
    phase = live_phase(phases)
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
        return _skip_pending(phases, now) + [
            Step("session_abandoned", reason="pause_overflow", phase_seq=phase.seq, at=now)
        ]
    phase.paused_seconds = (phase.paused_seconds or 0) + extra
    phase.pause_started_at = None
    phase.status = ACTIVE
    return [Step("phase_resumed", phase_seq=phase.seq, at=now, extra={"n": phase.pause_count})]


def advance(session: FocusSession, phases: list[FocusPhase], now: datetime) -> list[Step]:
    """User tap: begin the pending focus phase, or skip a running break."""
    live = live_phase(phases)
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


def _bank_open_pause(phase: FocusPhase, now: datetime) -> None:
    """Fold an in-flight pause into paused_seconds and clear the anchor."""
    if phase.status == PAUSED and phase.pause_started_at is not None:
        phase.paused_seconds = (phase.paused_seconds or 0) + int(
            (now - (_aware(phase.pause_started_at) or now)).total_seconds()
        )
        phase.pause_started_at = None


def _abandon_speedrun(
    session: FocusSession,
    live: FocusPhase,
    phases: list[FocusPhase],
    now: datetime,
    elapsed: int,
    reason: str,
) -> tuple[Step, list[Step]]:
    """A dead speedrun is a failed run, not a manual stop — the
    speedrun_failed step carries the HP cost so no session_abandoned step
    is emitted (emitting both would double-charge)."""
    live.status = ABANDONED
    live.ended_at = now
    session.status = S_ABANDONED
    session.ended_at = now
    stype = speedrun_type(session, live)
    result = "miss" if stype == "time_boxed" else "abandoned"
    _speedrun_result(session, result, elapsed, reason=reason)
    return (
        Step(
            "speedrun_failed",
            phase_seq=live.seq,
            at=now,
            scored=True,
            reason=reason,
            extra={
                "speedrun_type": stype,
                "elapsed_seconds": elapsed,
            },
        ),
        [Step("phase_abandoned", phase_seq=live.seq, at=now)] + _skip_pending(phases, now),
    )


def stop(session: FocusSession, phases: list[FocusPhase], now: datetime) -> tuple[Step, list[Step]]:
    """End the session now. Returns (final_step, scored_steps) — a stopwatch
    stop may emit milestone steps before the end step."""
    scored: list[Step] = []
    live = live_phase(phases)
    if live is not None and live.kind == SPEEDRUN:
        started = _aware(live.started_at) or now
        _bank_open_pause(live, now)
        return _abandon_speedrun(
            session, live, phases, now, max(0, int((now - started).total_seconds())), "abandon"
        )
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
                scored + _skip_pending(phases, now),
            )
    session.status = S_ENDED
    session.ended_at = now
    return Step("session_ended", at=now), scored + _skip_pending(phases, now)


def done(
    session: FocusSession,
    phases: list[FocusPhase],
    now: datetime,
    prior_record_seconds: int | None = None,
) -> list[Step]:
    """User-declared finish — the speedrun win path.

    Elapsed is wall-clock (pause-inclusive: the countdown kept ticking).
    time_boxed wins under its budget; beat_best always finishes — the
    caller-supplied prior record decides whether it's also a record run
    (the service re-reads the record inside the txn, so the engine stays
    DB-free). beat_best records are additionally gated at MIN_RECORD_SECONDS:
    a sub-minute finish completes as "finished" without record, bonus or
    board — an unbeatable 5s "record" would brick the label's board. The
    phase_completed step is deliberately unscored — it lands in the ledger
    so the feed can reconstruct the run, while the speedrun_completed step
    carries the actual reward.
    """
    live = live_phase(phases)
    if live is None or live.kind != SPEEDRUN:
        raise ValueError("no live speedrun phase to finish")
    started = _aware(live.started_at) or now
    elapsed = max(0, int((now - started).total_seconds()))
    if elapsed < 1:
        # A sub-second "win" lands a completed phase with actual_seconds=0 —
        # the label's beat_best board (MIN over completed runs) could never
        # be beaten again. Rejected before ANY mutation; the run stays live.
        raise ValueError("run too short")
    _bank_open_pause(live, now)
    stype = speedrun_type(session, live)
    if stype == "time_boxed" and elapsed >= live.planned_seconds:
        # evaluate() owns this transition and would already have failed the
        # run — unreachable while the session is live; keep the guard so a
        # late done() can't claim a deadline that already passed.
        final, pre = _abandon_speedrun(session, live, phases, now, elapsed, "timeout")
        return pre + [final]
    live.status = COMPLETED
    live.actual_seconds = elapsed
    live.ended_at = now
    session.status = S_ENDED
    session.ended_at = now
    steps = [
        Step(
            "phase_completed",
            phase_seq=live.seq,
            at=now,
            actual_seconds=elapsed,
            scored=False,
        )
    ]
    if stype == "time_boxed":
        _speedrun_result(session, "win", elapsed, margin_seconds=live.planned_seconds - elapsed)
        steps.append(
            Step(
                "speedrun_completed",
                phase_seq=live.seq,
                at=now,
                scored=True,
                extra={
                    "speedrun_type": "time_boxed",
                    "elapsed_seconds": elapsed,
                    # The floor gates the bonus too — a sub-minute finish is
                    # still a "win" but earns no speedrun-specific credit
                    # (kills the start→done→repeat bonus farm; result and
                    # duration XP are unchanged).
                    "win_bonus": elapsed >= MIN_RECORD_SECONDS,
                    "under_budget": True,
                    "margin_seconds": live.planned_seconds - elapsed,
                },
            )
        )
    else:
        record = elapsed >= MIN_RECORD_SECONDS and (
            prior_record_seconds is None or elapsed < prior_record_seconds
        )
        _speedrun_result(
            session,
            "record" if record else "finished",
            elapsed,
            old_record_seconds=prior_record_seconds,
        )
        steps.append(
            Step(
                "speedrun_completed",
                phase_seq=live.seq,
                at=now,
                scored=True,
                extra={
                    "speedrun_type": "beat_best",
                    "elapsed_seconds": elapsed,
                    # The win bonus pays on record runs only — a non-record
                    # finish still earns its duration XP.
                    "win_bonus": record,
                    "record": record,
                    "old_record_seconds": prior_record_seconds,
                },
            )
        )
        if record:
            steps.append(
                Step(
                    "record_set",
                    phase_seq=live.seq,
                    at=now,
                    scored=True,
                    extra={
                        "activity_label": session.activity_label,
                        "old_seconds": prior_record_seconds,
                        "new_seconds": elapsed,
                    },
                )
            )
    steps.append(Step("session_ended", at=now))
    return steps
