"""Unit tests for the pure wall-clock session state machine."""

from datetime import datetime, timedelta, timezone

from app.game import session_engine as se
from app.models.game import FocusPhase, FocusSession

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _session(**kw) -> FocusSession:
    kw.setdefault("mode", "timer")
    return FocusSession(
        user_id=1,
        status="active",
        preset={"difficulty": "easy", "auto_start_breaks": True, "auto_start_focus": False},
        pause_budget_count=3,
        pause_budget_seconds=300,
        started_at=T0,
        **kw,
    )


def _phase(
    session_id: int, seq: int, kind: str, status: str, planned: int, started_at=None
) -> FocusPhase:
    return FocusPhase(
        session_id=session_id,
        seq=seq,
        kind=kind,
        status=status,
        planned_seconds=planned,
        started_at=started_at,
    )


def _pomodoro(statuses=("active", "pending", "pending")) -> list[FocusPhase]:
    kinds = ["focus", "break", "focus"]
    return [
        _phase(1, i, k, s, (1500 if k == "focus" else 300), T0 if s != "pending" else None)
        for i, (k, s) in enumerate(zip(kinds, statuses, strict=True))
    ]


class TestEvaluate:
    def test_active_phase_not_elapsed_no_steps(self):
        s, phases = _session(), _pomodoro()
        assert se.evaluate(s, phases, T0 + timedelta(minutes=10)) == []
        assert s.status == "active"

    def test_phase_completes_break_autostarts(self):
        s, phases = _session(), _pomodoro()
        steps = se.evaluate(s, phases, T0 + timedelta(minutes=26))
        kinds = [st.kind for st in steps]
        assert kinds == ["phase_completed", "phase_started"]
        assert steps[0].scored is True
        assert phases[0].status == "completed"
        assert phases[1].status == "active"
        assert phases[1].started_at == T0 + timedelta(minutes=25)

    def test_full_plan_completes_session(self):
        s = _session()
        s.preset["auto_start_focus"] = True  # chain through every phase
        phases = _pomodoro()
        steps = se.evaluate(s, phases, T0 + timedelta(minutes=56))
        assert phases[0].status == "completed"
        assert phases[1].status == "completed"
        assert phases[2].status == "completed"
        assert s.status == "ended"
        assert steps[-1].kind == "session_ended"

    def test_pending_past_grace_clean_end(self):
        s, phases = _session(), _pomodoro()
        # focus ends at +25, break at +30, pending grace +5 -> ends at +35.
        steps = se.evaluate(s, phases, T0 + timedelta(minutes=36))
        assert s.status == "ended"
        assert steps[-1].kind == "session_ended"
        # The untapped pending phase is closed out, not left startable.
        assert steps[-2].kind == "phase_skipped"
        assert phases[2].status == "skipped"

    def test_absence_grace_abandon_with_zero_completed(self):
        """Pending phase past grace with no completed focus -> abandon.
        Reachable when a session's first phase is still pending (e.g. a
        crafted/future state); unreachable through normal play because the
        first phase always starts active."""
        s = _session()
        phases = [_phase(1, 0, "focus", "pending", 1500)]
        steps = se.evaluate(s, phases, T0 + timedelta(seconds=400))
        assert s.status == "abandoned"
        assert steps == [
            se.Step("phase_skipped", phase_seq=0, at=T0 + timedelta(seconds=300)),
            se.Step("session_abandoned", reason="absence_grace", at=T0 + timedelta(seconds=300)),
        ]

    def test_pause_overflow_abandons(self):
        s = _session()
        phases = _pomodoro()
        phases[0].status = "paused"
        phases[0].pause_started_at = T0
        phases[0].paused_seconds = 100
        steps = se.evaluate(s, phases, T0 + timedelta(seconds=250))
        assert s.status == "abandoned"
        # Never-started phases close out skipped — a dead session can't
        # leave them 'pending' reading as still startable.
        assert [st.kind for st in steps] == [
            "phase_skipped",
            "phase_skipped",
            "session_abandoned",
        ]
        assert steps[-1].reason == "pause_overflow"
        assert phases[0].status == "abandoned"
        assert phases[1].status == "skipped"
        assert phases[2].status == "skipped"

    def test_pause_within_budget_no_steps(self):
        s = _session()
        phases = _pomodoro()
        phases[0].status = "paused"
        phases[0].pause_started_at = T0
        steps = se.evaluate(s, phases, T0 + timedelta(seconds=200))
        assert steps == []
        assert s.status == "active"

    def test_auto_start_focus_chains(self):
        s = _session()
        s.preset["auto_start_focus"] = True
        phases = _pomodoro()
        se.evaluate(s, phases, T0 + timedelta(minutes=31))
        assert phases[2].status == "active"  # auto-started right after break

    def test_grace_anchors_last_phase_end_across_calls(self):
        """Bug: anchor was session.started_at — every cross-call advance died."""
        s, phases = _session(), _pomodoro()
        # Call 1 at +32m: focus ends +25m, break ends +30m, focus pending.
        se.evaluate(s, phases, T0 + timedelta(minutes=32))
        assert phases[2].status == "pending"
        assert s.status == "active"
        # Call 2 at +33m (inside break_end+grace=+35m): must stay active.
        se.evaluate(s, phases, T0 + timedelta(minutes=33))
        assert s.status == "active"
        assert phases[2].status == "pending"
        # Past grace (+36m): clean end anchored at +35m.
        se.evaluate(s, phases, T0 + timedelta(minutes=36))
        assert s.status == "ended"
        assert s.ended_at == T0 + timedelta(minutes=35)


class TestVerbs:
    def test_manual_stop_zero_completed_abandons(self):
        s, phases = _session(), _pomodoro()
        final, _ = se.stop(s, phases, T0 + timedelta(minutes=10))
        assert s.status == "abandoned"
        assert final.reason == "manual_stop"

    def test_manual_stop_with_completed_clean_end(self):
        s, phases = _session(), _pomodoro(("completed", "active", "pending"))
        final, _ = se.stop(s, phases, T0 + timedelta(minutes=26))
        assert s.status == "ended"
        assert final.kind == "session_ended"
        assert phases[1].status == "skipped"

    def test_fourth_pause_abandons(self):
        s, phases = _session(), _pomodoro()
        phases[0].pause_count = 3
        steps = se.pause(s, phases, T0 + timedelta(minutes=5))
        assert s.status == "abandoned"
        assert steps[-1].reason == "pause_overflow"
        # The count-overflow abandon closes pending phases out too.
        assert [p.status for p in phases] == ["abandoned", "skipped", "skipped"]

    def test_resume_seconds_overflow_skips_pending(self):
        """Resume after the seconds budget blew abandons — pending phases
        must skip, not dangle (the third pause-overflow abandon path)."""
        s, phases = _session(), _pomodoro()
        phases[0].status = "paused"
        phases[0].pause_started_at = T0
        phases[0].paused_seconds = 100
        steps = se.resume(s, phases, T0 + timedelta(seconds=250))  # 100+250 > 300
        assert s.status == "abandoned"
        assert [st.kind for st in steps] == [
            "phase_skipped",
            "phase_skipped",
            "session_abandoned",
        ]
        assert steps[-1].reason == "pause_overflow"
        assert [p.status for p in phases] == ["abandoned", "skipped", "skipped"]

    def test_advance_pending_starts_phase(self):
        s, phases = _session(), _pomodoro(("completed", "completed", "pending"))
        steps = se.advance(s, phases, T0 + timedelta(minutes=31))
        assert phases[2].status == "active"
        assert steps[0].kind == "phase_started"

    def test_advance_skipping_break_emits_skip_step(self):
        s, phases = _session(), _pomodoro(("completed", "active", "pending"))
        steps = se.advance(s, phases, T0 + timedelta(minutes=27))
        assert phases[1].status == "skipped"
        assert [st.kind for st in steps] == ["phase_skipped", "phase_started"]

    def test_advance_while_running_rejected(self):
        s, phases = _session(), _pomodoro()
        import pytest

        with pytest.raises(ValueError):
            se.advance(s, phases, T0 + timedelta(minutes=5))

    def test_stopwatch_stop_pays_milestones(self):
        s = _session(mode="stopwatch")
        phases = [_phase(1, 0, "stopwatch", "active", 0, T0)]
        final, scored = se.stop(s, phases, T0 + timedelta(minutes=55))
        assert s.status == "ended"
        assert len(scored) == 2  # 25 and 50 minute milestones
        assert phases[0].status == "completed"

    def test_stopwatch_paused_stop_excludes_open_pause(self):
        """Bug: in-flight pause counted as focus time -> free milestones."""
        s = _session(mode="stopwatch")
        phases = [_phase(1, 0, "stopwatch", "paused", 0, T0)]
        phases[0].paused_seconds = 60
        phases[0].pause_started_at = T0 + timedelta(minutes=40)
        # Stop at +50m: open pause 10m + banked 60s -> actual ~39m -> 1 milestone
        # (buggy code counted the open pause: 50m -> 2 milestones).
        _, scored = se.stop(s, phases, T0 + timedelta(minutes=50))
        assert len(scored) == 1

    def test_stop_during_break_zero_completed_abandons(self):
        """0 completed focus + any live phase stopped -> manual_stop abandon."""
        s = _session()
        phases = [_phase(1, 0, "break", "active", 300, T0), _phase(1, 1, "focus", "pending", 1500)]
        final, _ = se.stop(s, phases, T0 + timedelta(minutes=1))
        assert s.status == "abandoned"
        assert final.reason == "manual_stop"
        assert phases[0].status == "skipped"


def _speedrun_session(kind="time_boxed", budget_seconds=600, target=None) -> FocusSession:
    blob = (
        {"type": "time_boxed", "budget_seconds": budget_seconds}
        if kind == "time_boxed"
        else {"type": "beat_best", "target_seconds": target}
    )
    return _session(mode="speedrun", speedrun=blob, activity_label="5k")


def _speedrun_phase(status="active", planned=600, started_at=T0) -> FocusPhase:
    return _phase(1, 0, "speedrun", status, planned, started_at)


class TestSpeedrun:
    def test_time_boxed_inside_budget_no_steps(self):
        s = _speedrun_session()
        phases = [_speedrun_phase()]
        assert se.evaluate(s, phases, T0 + timedelta(seconds=599)) == []
        assert s.status == "active"

    def test_time_boxed_deadline_boundary_misses(self):
        """elapsed == planned -> miss: the deadline owns the run, not done()."""
        s = _speedrun_session()
        phases = [_speedrun_phase()]
        steps = se.evaluate(s, phases, T0 + timedelta(seconds=600))
        assert s.status == "abandoned"
        assert phases[0].status == "abandoned"
        assert [st.kind for st in steps] == ["phase_abandoned", "speedrun_failed"]
        assert steps[-1].reason == "timeout"
        assert steps[-1].scored is True
        assert s.speedrun["result"] == "miss"
        assert s.speedrun["elapsed_seconds"] == 600

    def test_paused_time_boxed_still_fails_on_deadline(self):
        """Pauses never extend the countdown — a run parked at the deadline
        dies anyway, and the open pause banks into paused_seconds."""
        s = _speedrun_session()
        phase = _speedrun_phase(status="paused")
        phase.pause_started_at = T0 + timedelta(seconds=400)
        phase.paused_seconds = 100
        phases = [phase]
        steps = se.evaluate(s, phases, T0 + timedelta(seconds=700))
        assert s.status == "abandoned"
        assert steps[-1].kind == "speedrun_failed"
        # Open pause banks only to the deadline (T0+600): 100 banked + 200
        # open — the pause can't accrue past the moment the run died.
        assert phase.paused_seconds == 300
        assert phase.pause_started_at is None

    def test_beat_best_is_open_ended(self):
        """planned_seconds=0 just sits — paused or active, never times out."""
        s = _speedrun_session(kind="beat_best", target=500)
        phases = [_speedrun_phase(planned=0)]
        assert se.evaluate(s, phases, T0 + timedelta(hours=5)) == []
        assert s.status == "active"

    def test_beat_best_paused_never_overflows(self):
        """The pause-overflow check is skipped for speedrun kinds."""
        s = _speedrun_session(kind="beat_best")
        phase = _speedrun_phase(status="paused", planned=0)
        phase.pause_started_at = T0
        assert se.evaluate(s, [phase], T0 + timedelta(hours=2)) == []
        assert s.status == "active"

    def test_pause_speedrun_ignores_count_budget(self):
        s = _speedrun_session()
        phase = _speedrun_phase()
        phase.pause_count = 3  # at the timer-mode budget — must still pause
        steps = se.pause(s, [phase], T0 + timedelta(minutes=1))
        assert [st.kind for st in steps] == ["phase_paused"]
        assert s.status == "active"

    def test_resume_banks_without_budget_check(self):
        s = _speedrun_session()
        phase = _speedrun_phase(status="paused")
        phase.pause_started_at = T0
        se.resume(s, [phase], T0 + timedelta(seconds=500))  # past the 300s budget
        assert phase.paused_seconds == 500
        assert s.status == "active"

    def test_stop_abandons_with_speedrun_failed_not_session_abandoned(self):
        """Manual stop on a live run is an abandon — and must not emit a
        session_abandoned step on top (that would double-charge HP)."""
        s = _speedrun_session()
        phases = [_speedrun_phase()]
        final, steps = se.stop(s, phases, T0 + timedelta(seconds=120))
        assert s.status == "abandoned"
        assert phases[0].status == "abandoned"
        assert final.kind == "speedrun_failed"
        assert final.reason == "abandon"
        assert all(st.kind != "session_abandoned" for st in steps + [final])
        assert s.speedrun["result"] == "miss"

    def test_done_time_boxed_under_budget_wins(self):
        s = _speedrun_session()
        phases = [_speedrun_phase()]
        steps = se.done(s, phases, T0 + timedelta(seconds=500))
        assert s.status == "ended"
        assert phases[0].status == "completed"
        assert phases[0].actual_seconds == 500
        kinds = [st.kind for st in steps]
        assert kinds == ["phase_completed", "speedrun_completed", "session_ended"]
        assert steps[0].scored is False  # feed reconstruction only
        assert steps[1].scored is True
        assert steps[1].extra["win_bonus"] is True
        assert steps[1].extra["margin_seconds"] == 100
        assert s.speedrun["result"] == "win"
        assert s.speedrun["margin_seconds"] == 100  # same value the event carries

    def test_done_time_boxed_at_deadline_is_miss(self):
        """The guard: a done() racing the deadline can't claim the win."""
        s = _speedrun_session()
        phases = [_speedrun_phase()]
        steps = se.done(s, phases, T0 + timedelta(seconds=600))
        assert s.status == "abandoned"
        assert [st.kind for st in steps] == ["phase_abandoned", "speedrun_failed"]
        assert steps[-1].reason == "timeout"

    def test_done_beat_best_first_run_sets_record(self):
        s = _speedrun_session(kind="beat_best", target=None)
        phases = [_speedrun_phase(planned=0)]
        steps = se.done(s, phases, T0 + timedelta(seconds=300), prior_record_seconds=None)
        kinds = [st.kind for st in steps]
        assert kinds == ["phase_completed", "speedrun_completed", "record_set", "session_ended"]
        assert steps[2].extra["old_seconds"] is None
        assert steps[2].extra["new_seconds"] == 300
        assert steps[1].extra["record"] is True
        assert steps[1].extra["win_bonus"] is True
        assert s.speedrun["result"] == "record"

    def test_done_beat_best_slower_than_record_finishes(self):
        """A non-record finish still completes — duration XP, no bonus,
        no record_set step."""
        s = _speedrun_session(kind="beat_best", target=200)
        phases = [_speedrun_phase(planned=0)]
        steps = se.done(s, phases, T0 + timedelta(seconds=300), prior_record_seconds=200)
        kinds = [st.kind for st in steps]
        assert kinds == ["phase_completed", "speedrun_completed", "session_ended"]
        assert steps[1].extra["record"] is False
        assert steps[1].extra["win_bonus"] is False
        assert steps[1].extra["old_record_seconds"] == 200
        assert s.speedrun["result"] == "finished"
        assert s.speedrun["old_record_seconds"] == 200

    def test_done_beat_best_faster_than_record_sets_record(self):
        s = _speedrun_session(kind="beat_best", target=400)
        phases = [_speedrun_phase(planned=0)]
        steps = se.done(s, phases, T0 + timedelta(seconds=300), prior_record_seconds=400)
        kinds = [st.kind for st in steps]
        assert "record_set" in kinds
        record = steps[kinds.index("record_set")]
        assert record.extra["old_seconds"] == 400
        assert record.extra["new_seconds"] == 300

    def test_done_on_non_speedrun_raises(self):
        s, phases = _session(), _pomodoro()
        import pytest

        with pytest.raises(ValueError):
            se.done(s, phases, T0 + timedelta(minutes=5))

    def test_done_subsecond_rejected_without_mutation(self):
        """elapsed==0 must never land a completed phase — actual_seconds=0
        poisons the label's record board (MIN can't go below it). Rejected
        before any mutation; the run stays fully live."""
        s = _speedrun_session()
        phases = [_speedrun_phase()]
        import pytest

        with pytest.raises(ValueError):
            se.done(s, phases, T0)
        assert s.status == "active"
        assert s.ended_at is None
        assert "result" not in s.speedrun
        assert phases[0].status == "active"
        assert phases[0].actual_seconds is None
        assert phases[0].ended_at is None

    def test_done_subsecond_rejection_runs_before_pause_banking(self):
        """A paused run rejected at elapsed==0 keeps its open pause — the
        guard precedes _bank_open_pause."""
        s = _speedrun_session()
        phase = _speedrun_phase(status="paused")
        phase.pause_started_at = T0
        import pytest

        with pytest.raises(ValueError):
            se.done(s, [phase], T0)
        assert phase.status == "paused"
        assert phase.pause_started_at == T0
        assert phase.paused_seconds in (None, 0)

    def test_done_subsecond_beat_best_rejected(self):
        """The board poison is a beat_best hazard but the guard covers both
        kinds — a 0s run is never a legal finish."""
        s = _speedrun_session(kind="beat_best")
        import pytest

        with pytest.raises(ValueError):
            se.done(s, [_speedrun_phase(planned=0)], T0)
        assert s.status == "active"
        assert "result" not in s.speedrun

    def test_done_at_one_second_still_wins(self):
        """The guard's lower boundary: elapsed==1 is a legal run, and the
        win blob carries the same margin the event does."""
        s = _speedrun_session()
        phases = [_speedrun_phase()]
        steps = se.done(s, phases, T0 + timedelta(seconds=1))
        assert s.status == "ended"
        assert steps[1].extra["margin_seconds"] == 599
        assert s.speedrun["result"] == "win"
        assert s.speedrun["margin_seconds"] == 599

    def test_done_beat_best_one_second_still_records(self):
        """elapsed==1 on a first beat_best run stays a record, and the blob
        exposes the (null) prior it was judged against."""
        s = _speedrun_session(kind="beat_best", target=None)
        phases = [_speedrun_phase(planned=0)]
        steps = se.done(s, phases, T0 + timedelta(seconds=1), prior_record_seconds=None)
        assert s.speedrun["result"] == "record"
        assert s.speedrun["old_record_seconds"] is None
        assert steps[2].extra["new_seconds"] == 1
