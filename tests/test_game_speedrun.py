"""API tests for speedrun sessions (#69) — time-boxed and beat-your-best.

Same time-travel convention as test_game_sessions: rewind row timestamps,
then let the next call's wall-clock evaluation replay the transition.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.game import session_service
from app.models.game import Achievement, FocusPhase, FocusSession, GameEvent, UserAchievement
from app.models.notification import Notification, NotificationType

SESSIONS = "/api/v1/game/sessions"
EVENTS = "/api/v1/game/events"
ACTIVITY = "/api/v1/game/activity"


@pytest.fixture(autouse=True)
def _seeded_rng(monkeypatch) -> None:
    """Deterministic crit rolls: seed 0's early draws stay above crit chance."""
    import random

    monkeypatch.setattr(session_service, "_rng", random.Random(0))


def _ago(seconds: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


async def _start_time_boxed(client: AsyncClient, budget_minutes: int = 10, **overrides) -> dict:
    body = {
        "mode": "speedrun",
        "speedrun": {"kind": "time_boxed", "budget_minutes": budget_minutes},
        **overrides,
    }
    response = await client.post(SESSIONS, json=body)
    assert response.status_code == 201, response.text
    return response.json()["session"]


async def _start_beat_best(client: AsyncClient, label: str = "5k", **overrides) -> dict:
    body = {
        "mode": "speedrun",
        "activity_label": label,
        "speedrun": {"kind": "beat_best"},
        **overrides,
    }
    response = await client.post(SESSIONS, json=body)
    assert response.status_code == 201, response.text
    return response.json()["session"]


async def _rewind_phase(db: AsyncSession, session_id: int, seconds: int, seq: int = 0) -> None:
    await db.execute(
        update(FocusPhase)
        .where(FocusPhase.session_id == session_id, FocusPhase.seq == seq)
        .values(started_at=_ago(seconds))
    )
    await db.commit()


async def _events(db: AsyncSession, event_type: str) -> list[GameEvent]:
    rows = await db.execute(select(GameEvent).where(GameEvent.type == event_type))
    return list(rows.scalars().all())


class TestStart:
    async def test_time_boxed_start_builds_single_phase_and_blob(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start_time_boxed(authenticated_async_client, budget_minutes=10)
        assert session["mode"] == "speedrun"
        assert session["speedrun"] == {"type": "time_boxed", "budget_seconds": 600}
        assert [p["kind"] for p in session["phases"]] == ["speedrun"]
        assert session["phases"][0]["planned_seconds"] == 600
        assert session["phases"][0]["status"] == "active"
        started = (await _events(db, "session_started"))[0]
        assert started.payload["speedrun"] == {"type": "time_boxed", "budget_seconds": 600}

    async def test_beat_best_start_snapshots_null_target(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        session = await _start_beat_best(authenticated_async_client)
        assert session["speedrun"] == {"type": "beat_best", "target_seconds": None}
        assert session["phases"][0]["planned_seconds"] == 0

    async def test_start_ignores_phases_for_speedrun(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        body = {
            "mode": "speedrun",
            "phases": [{"kind": "focus", "minutes": 10}],
            "speedrun": {"kind": "time_boxed", "budget_minutes": 10},
        }
        r = await authenticated_async_client.post(SESSIONS, json=body)
        assert r.status_code == 201
        assert [p["kind"] for p in r.json()["session"]["phases"]] == ["speedrun"]

    @pytest.mark.parametrize(
        "body",
        [
            {"mode": "speedrun"},
            {"mode": "speedrun", "speedrun": {"kind": "time_boxed"}},
            {
                "mode": "speedrun",
                "activity_label": "5k",
                "speedrun": {"kind": "beat_best", "budget_minutes": 10},
            },
            {"mode": "speedrun", "speedrun": {"kind": "beat_best"}},
            {
                "mode": "timer",
                "phases": [{"kind": "focus", "minutes": 10}],
                "speedrun": {"kind": "time_boxed", "budget_minutes": 10},
            },
        ],
    )
    async def test_bad_speedrun_combos_rejected(
        self, authenticated_async_client: AsyncClient, body: dict
    ) -> None:
        """Missing config, missing budget, budget on beat_best, missing
        label, and a stray speedrun blob on timer mode all 400."""
        response = await authenticated_async_client.post(SESSIONS, json=body)
        assert response.status_code == 400, response.text

    async def test_out_of_range_budget_is_422(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        response = await authenticated_async_client.post(
            SESSIONS,
            json={
                "mode": "speedrun",
                "speedrun": {"kind": "time_boxed", "budget_minutes": 0},
            },
        )
        assert response.status_code == 422


class TestDone:
    async def test_done_under_budget_wins_and_pays_bonus(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start_time_boxed(authenticated_async_client, budget_minutes=10)
        sid = session["id"]
        await _rewind_phase(db, sid, 5 * 60)  # 5min into a 10min budget
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/done")
        body = r.json()
        assert r.status_code == 200
        assert body["session"]["status"] == "ended"
        assert body["session"]["phases"][0]["status"] == "completed"
        assert body["session"]["phases"][0]["actual_seconds"] == pytest.approx(5 * 60, abs=2)
        assert body["session"]["speedrun"]["result"] == "win"
        # 5 minutes * 1 XP + 25 win bonus, easy difficulty.
        assert body["profile"]["xp_today"] == 30
        completed = (await _events(db, "speedrun_completed"))[0]
        assert completed.payload["under_budget"] is True
        assert completed.payload["margin_seconds"] == pytest.approx(5 * 60, abs=2)
        assert completed.payload["win_bonus"] is True

    async def test_done_at_exact_budget_misses_on_evaluate(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """elapsed == planned -> the deadline already owns it: done()'s
        evaluate leg fails the run before the verb can claim the win."""
        session = await _start_time_boxed(authenticated_async_client, budget_minutes=10)
        sid = session["id"]
        await _rewind_phase(db, sid, 10 * 60)
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/done")
        body = r.json()
        assert body["session"]["status"] == "abandoned"
        assert body["session"]["speedrun"]["result"] == "miss"
        assert body["profile"]["hp"] < body["profile"]["max_hp"]
        failed = (await _events(db, "speedrun_failed"))[0]
        assert failed.payload["reason"] == "timeout"

    async def test_paused_run_still_times_out(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Parking the run past the deadline does not save it — the
        countdown ignores banked pause time."""
        session = await _start_time_boxed(authenticated_async_client, budget_minutes=10)
        sid = session["id"]
        await _rewind_phase(db, sid, 5 * 60)
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/pause")
        assert r.status_code == 200
        # Rewind BOTH clocks: phase start 11min ago, pause start 6min ago.
        await _rewind_phase(db, sid, 11 * 60)
        await db.execute(
            update(FocusPhase)
            .where(FocusPhase.session_id == sid, FocusPhase.seq == 0)
            .values(pause_started_at=_ago(6 * 60))
        )
        await db.commit()
        r = await authenticated_async_client.get(f"{SESSIONS}/{sid}")
        assert r.json()["session"]["status"] == "abandoned"
        assert (await _events(db, "speedrun_failed"))[0].payload["reason"] == "timeout"

    async def test_done_on_non_speedrun_is_400(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        r = await authenticated_async_client.post(
            SESSIONS, json={"mode": "timer", "phases": [{"kind": "focus", "minutes": 10}]}
        )
        sid = r.json()["session"]["id"]
        response = await authenticated_async_client.post(f"{SESSIONS}/{sid}/done")
        assert response.status_code == 400

    async def test_done_subsecond_is_400_and_run_stays_live(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """The sub-second window is real: int() truncates 0.7s to 0 — a 0s
        'win' would poison the label's record board. The engine rejects it,
        the verb's ValueError lands as a 400, and nothing mutated."""
        session = await _start_time_boxed(authenticated_async_client)
        sid = session["id"]
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/done")
        assert r.status_code == 400, r.text
        view = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        assert view["session"]["status"] == "active"
        assert view["session"]["phases"][0]["status"] == "active"
        assert "result" not in view["session"]["speedrun"]
        assert await _events(db, "speedrun_completed") == []
        assert await _events(db, "speedrun_failed") == []

    async def test_done_subsecond_beat_best_is_400(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        """Beat-your-best shares the guard — it's the kind whose record
        board the 0s run would poison."""
        session = await _start_beat_best(authenticated_async_client)
        r = await authenticated_async_client.post(f"{SESSIONS}/{session['id']}/done")
        assert r.status_code == 400, r.text
        view = (await authenticated_async_client.get(f"{SESSIONS}/{session['id']}")).json()
        assert view["session"]["status"] == "active"

    async def test_done_at_one_second_still_wins(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start_time_boxed(authenticated_async_client, budget_minutes=10)
        await _rewind_phase(db, session["id"], 1)
        r = await authenticated_async_client.post(f"{SESSIONS}/{session['id']}/done")
        assert r.status_code == 200, r.text
        assert r.json()["session"]["speedrun"]["result"] == "win"

    async def test_done_win_blob_carries_margin_seconds(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """FE contract: the win blob carries the same margin_seconds the
        speedrun_completed event does."""
        session = await _start_time_boxed(authenticated_async_client, budget_minutes=10)
        await _rewind_phase(db, session["id"], 5 * 60)
        r = await authenticated_async_client.post(f"{SESSIONS}/{session['id']}/done")
        blob = r.json()["session"]["speedrun"]
        assert blob["result"] == "win"
        assert blob["margin_seconds"] == pytest.approx(5 * 60, abs=2)

    async def test_done_with_corrupt_speedrun_blob_does_not_500(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Service type-detection mirrors the engine: a non-dict blob (only
        writable via DB surgery, never the API) can't 500 the record read —
        planned_seconds classifies the run."""
        session = await _start_time_boxed(authenticated_async_client, budget_minutes=10)
        sid = session["id"]
        await db.execute(
            update(FocusSession).where(FocusSession.id == sid).values(speedrun="corrupt")
        )
        await db.commit()
        await _rewind_phase(db, sid, 5 * 60)
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/done")
        assert r.status_code == 200, r.text
        assert r.json()["session"]["speedrun"]["result"] == "win"


class TestFail:
    async def test_stop_abandons_and_costs_hp(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start_time_boxed(authenticated_async_client)
        r = await authenticated_async_client.post(f"{SESSIONS}/{session['id']}/stop")
        body = r.json()
        assert body["session"]["status"] == "abandoned"
        assert body["session"]["speedrun"]["result"] == "miss"
        assert body["profile"]["hp"] < body["profile"]["max_hp"]
        failed = (await _events(db, "speedrun_failed"))[0]
        assert failed.payload["reason"] == "abandon"
        # No session_abandoned on top — that would double-charge HP.
        assert await _events(db, "session_abandoned") == []

    async def test_beat_best_stop_marks_abandoned(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start_beat_best(authenticated_async_client)
        r = await authenticated_async_client.post(f"{SESSIONS}/{session['id']}/stop")
        body = r.json()
        assert body["session"]["status"] == "abandoned"
        assert body["session"]["speedrun"]["result"] == "abandoned"
        assert body["profile"]["hp"] < body["profile"]["max_hp"]

    async def test_timeout_via_evaluate_costs_hp(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A run left past the deadline fails on the next read."""
        session = await _start_time_boxed(authenticated_async_client, budget_minutes=1)
        sid = session["id"]
        await _rewind_phase(db, sid, 61)
        r = await authenticated_async_client.get(f"{SESSIONS}/{sid}")
        body = r.json()
        assert body["session"]["status"] == "abandoned"
        assert body["profile"]["hp"] < body["profile"]["max_hp"]
        assert (await _events(db, "speedrun_failed"))[0].payload["reason"] == "timeout"


class TestRecords:
    async def _run_and_done(
        self, client: AsyncClient, db: AsyncSession, label: str, seconds: int
    ) -> dict:
        session = await _start_beat_best(client, label)
        return await self._finish(client, db, session, seconds)

    async def _finish(
        self, client: AsyncClient, db: AsyncSession, session: dict, seconds: int
    ) -> dict:
        """Rewind the run's phase and declare done — session ends."""
        await _rewind_phase(db, session["id"], seconds)
        r = await client.post(f"{SESSIONS}/{session['id']}/done")
        assert r.status_code == 200, r.text
        return r.json()

    async def test_first_run_sets_record_and_badges(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        body = await self._run_and_done(authenticated_async_client, db, "5k", 5 * 60)
        session = body["session"]
        assert session["speedrun"]["result"] == "record"
        record = (await _events(db, "record_set"))[0]
        assert record.payload["activity_label"] == "5k"
        assert record.payload["old_seconds"] is None
        assert record.payload["new_seconds"] == pytest.approx(5 * 60, abs=2)
        completed = (await _events(db, "speedrun_completed"))[0]
        assert completed.payload["record"] is True
        assert completed.payload["old_record_seconds"] is None
        # duration XP + win bonus on the record run.
        assert body["profile"]["xp_today"] == 30
        # The RECORD feed row lands with the label + old->new meta.
        rows = await db.execute(
            select(Notification).where(Notification.type == NotificationType.RECORD)
        )
        note = rows.scalar_one()
        assert "personal best" in note.title.lower()
        assert note.meta["activity_label"] == "5k"
        assert note.meta["old_seconds"] is None
        # The Record Breaker badge granted off the scored record_set row.
        earned = await db.execute(
            select(UserAchievement)
            .join(Achievement, UserAchievement.achievement_id == Achievement.id)
            .where(Achievement.key == "first-record")
        )
        assert earned.scalar_one_or_none() is not None

    async def test_second_run_faster_beats_record(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        await self._run_and_done(authenticated_async_client, db, "5k", 5 * 60)
        session = await _start_beat_best(authenticated_async_client)
        # The start blob snapshots the standing record as the target.
        assert session["speedrun"]["target_seconds"] == pytest.approx(5 * 60, abs=2)
        body = await self._finish(authenticated_async_client, db, session, 4 * 60)
        assert body["session"]["speedrun"]["result"] == "record"
        records = await _events(db, "record_set")
        assert len(records) == 2
        latest = sorted(records, key=lambda e: e.id)[-1]
        assert latest.payload["old_seconds"] == pytest.approx(5 * 60, abs=2)
        assert latest.payload["new_seconds"] == pytest.approx(4 * 60, abs=2)

    async def test_slower_run_finishes_without_record_or_bonus(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        first = await self._run_and_done(authenticated_async_client, db, "5k", 4 * 60)
        xp_after_first = first["profile"]["xp_today"]
        body = await self._run_and_done(authenticated_async_client, db, "5k", 6 * 60)
        assert body["session"]["status"] == "ended"
        assert body["session"]["speedrun"]["result"] == "finished"
        completed = sorted(await _events(db, "speedrun_completed"), key=lambda e: e.id)
        assert completed[-1].payload["record"] is False
        assert completed[-1].payload["old_record_seconds"] == pytest.approx(4 * 60, abs=2)
        # Non-record finish: duration XP (6 min) only, no win bonus, no
        # second record_set.
        assert body["profile"]["xp_today"] - xp_after_first == 6
        assert len(await _events(db, "record_set")) == 1

    async def test_record_blob_carries_old_record_seconds(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """FE contract: 'record'/'finished' blobs expose the standing record
        the run was judged against — null on a label's first run."""
        first = await self._run_and_done(authenticated_async_client, db, "5k", 5 * 60)
        assert first["session"]["speedrun"]["result"] == "record"
        assert first["session"]["speedrun"]["old_record_seconds"] is None
        second = await self._run_and_done(authenticated_async_client, db, "5k", 4 * 60)
        assert second["session"]["speedrun"]["result"] == "record"
        assert second["session"]["speedrun"]["old_record_seconds"] == pytest.approx(5 * 60, abs=2)
        third = await self._run_and_done(authenticated_async_client, db, "5k", 6 * 60)
        assert third["session"]["speedrun"]["result"] == "finished"
        assert third["session"]["speedrun"]["old_record_seconds"] == pytest.approx(4 * 60, abs=2)

    async def test_records_are_per_label(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        await self._run_and_done(authenticated_async_client, db, "5k", 5 * 60)
        body = await self._run_and_done(authenticated_async_client, db, "10k", 7 * 60)
        # A different label has its own board — first 10k run is a record.
        assert body["session"]["speedrun"]["result"] == "record"
        assert len(await _events(db, "record_set")) == 2

    async def test_speedrun_emits_no_focus_or_milestone_events(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """The speedrun phase pays through speedrun_completed — no
        focus_phase_completed or stopwatch_milestone rows may appear."""
        session = await _start_time_boxed(authenticated_async_client, budget_minutes=10)
        await _rewind_phase(db, session["id"], 5 * 60)
        await authenticated_async_client.post(f"{SESSIONS}/{session['id']}/done")
        assert await _events(db, "focus_phase_completed") == []
        assert await _events(db, "stopwatch_milestone") == []
        # But the phase transition is in the ledger for feed reconstruction.
        phase_done = await _events(db, "phase_completed")
        assert len(phase_done) == 1
        assert phase_done[0].payload["_outcome"]["scored"] is False


class TestTracking:
    async def test_pbs_aggregation_and_focus_minutes(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """PBs: per-label best + attempts + set_at; runs also count as focus
        minutes via the completed phase row."""
        records = TestRecords()
        await records._run_and_done(authenticated_async_client, db, "5k", 5 * 60)
        await records._run_and_done(authenticated_async_client, db, "5k", 4 * 60)
        await records._run_and_done(authenticated_async_client, db, "5k", 6 * 60)
        r = await authenticated_async_client.get(ACTIVITY + "/stats")
        assert r.status_code == 200, r.text
        pbs = r.json()["speedrun_pbs"]
        assert len(pbs) == 1
        pb = pbs[0]
        assert pb["activity_label"] == "5k"
        assert pb["best_seconds"] == pytest.approx(4 * 60, abs=2)
        assert pb["attempts"] == 3
        assert pb["set_at"] is not None
        # 15 minutes of completed speedrun phases count as focus time.
        assert r.json()["total_hours"] == pytest.approx(15 / 60, abs=0.02)


class TestForge:
    @pytest.mark.parametrize("event_type", ["speedrun_completed", "speedrun_failed", "record_set"])
    async def test_client_cannot_forge_speedrun_events(
        self, authenticated_async_client: AsyncClient, event_type: str
    ) -> None:
        response = await authenticated_async_client.post(
            EVENTS,
            json={
                "events": [
                    {
                        "client_event_id": f"forge-{event_type}",
                        "type": event_type,
                        "client_ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {"minutes": 99, "win_bonus": True},
                    }
                ]
            },
        )
        assert response.status_code == 422
