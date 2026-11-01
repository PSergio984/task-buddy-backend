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
        assert phases[2].status == "pending"

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
            se.Step("session_abandoned", reason="absence_grace", at=T0 + timedelta(seconds=300))
        ]

    def test_pause_overflow_abandons(self):
        s = _session()
        phases = _pomodoro()
        phases[0].status = "paused"
        phases[0].pause_started_at = T0
        phases[0].paused_seconds = 100
        steps = se.evaluate(s, phases, T0 + timedelta(seconds=250))
        assert s.status == "abandoned"
        assert steps[0].reason == "pause_overflow"
        assert phases[0].status == "abandoned"

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
        step = se.pause(s, phases[0], T0 + timedelta(minutes=5))
        assert s.status == "abandoned"
        assert step.reason == "pause_overflow"

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
