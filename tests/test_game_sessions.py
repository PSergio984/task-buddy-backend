"""API tests for /api/v1/game/sessions — the focus-session lifecycle.

Time travel is done by rewinding row timestamps directly (started_at /
pause_started_at) and letting the next call's wall-clock evaluation replay
the transitions — no sleeps, fully deterministic.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.game import session_service
from app.models.game import FocusPhase, FocusSession, GameEvent
from app.models.user import User

SESSIONS = "/api/v1/game/sessions"


@pytest.fixture(autouse=True)
def _seeded_rng(monkeypatch) -> None:
    """Deterministic crit rolls: seed 0's early draws stay above crit chance."""
    import random

    monkeypatch.setattr(session_service, "_rng", random.Random(0))


def _ago(seconds: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


async def _start(client: AsyncClient, **overrides) -> dict:
    body = {
        "mode": "timer",
        "phases": [
            {"kind": "focus", "minutes": 10},
            {"kind": "break", "minutes": 5},
            {"kind": "focus", "minutes": 10},
        ],
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


class TestStart:
    async def test_start_creates_session_and_phases(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        assert session["status"] == "active"
        assert session["mode"] == "timer"
        assert [p["kind"] for p in session["phases"]] == ["focus", "break", "focus"]
        assert session["phases"][0]["status"] == "active"
        assert session["phases"][0]["planned_seconds"] == 600

        rows = await db.execute(select(FocusPhase).where(FocusPhase.session_id == session["id"]))
        assert len(rows.scalars().all()) == 3

        events = await db.execute(select(GameEvent).where(GameEvent.type == "session_started"))
        assert events.scalar_one_or_none() is not None

    async def test_second_start_conflicts(self, authenticated_async_client: AsyncClient) -> None:
        await _start(authenticated_async_client)
        body = {"mode": "timer", "phases": [{"kind": "focus", "minutes": 10}]}
        response = await authenticated_async_client.post(SESSIONS, json=body)
        assert response.status_code == 409

    async def test_start_requires_phases_for_timer(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        response = await authenticated_async_client.post(SESSIONS, json={"mode": "timer"})
        assert response.status_code == 400

    async def test_start_caps_phase_count(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.post(
            SESSIONS,
            json={
                "mode": "timer",
                "phases": [{"kind": "focus", "minutes": 10}] * 40,
            },
        )
        assert response.status_code == 422

    async def test_start_validates_task_ownership(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        body = {
            "mode": "timer",
            "phases": [{"kind": "focus", "minutes": 10}],
            "task_id": 999999,
        }
        response = await authenticated_async_client.post(SESSIONS, json=body)
        assert response.status_code == 404  # nonexistent, not misreported 409

    async def test_stale_active_session_is_evaluated_not_conflicted(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A clock-dead 'active' row must not block a fresh start."""
        session = await _start(authenticated_async_client)
        await db.execute(
            update(FocusSession)
            .where(FocusSession.id == session["id"])
            .values(started_at=_ago(25 * 60))
        )
        await _rewind_phase(db, session["id"], 25 * 60)
        await db.commit()
        session2 = await _start(authenticated_async_client)
        assert session2["status"] == "active"
        assert session2["id"] != session["id"]

    async def test_absence_grace_abandon_break_first_plan(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Break-leading plan: break ends, focus never tapped, grace expires
        with 0 completed focus -> session_abandoned + HP loss."""
        body = {
            "mode": "timer",
            "phases": [
                {"kind": "break", "minutes": 5},
                {"kind": "focus", "minutes": 10},
            ],
        }
        r = await authenticated_async_client.post(SESSIONS, json=body)
        session = r.json()["session"]
        await _rewind_phase(db, session["id"], 15 * 60)
        r = await authenticated_async_client.get(f"{SESSIONS}/active")
        body = r.json()
        assert body["session"]["status"] == "abandoned"
        assert body["profile"]["hp"] < body["profile"]["max_hp"]
        events = await db.execute(select(GameEvent).where(GameEvent.type == "session_abandoned"))
        assert events.scalar_one().payload["reason"] == "absence_grace"

    async def test_server_prefixed_event_id_rejected(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        """Client can't squat server-generated eids to suppress events."""
        response = await authenticated_async_client.post(
            "/api/v1/game/events",
            json={
                "events": [
                    {
                        "client_event_id": "server:s1:session_abandoned:0:0:0",
                        "type": "focus_phase_completed",
                        "client_ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {"minutes": 10, "difficulty": "easy"},
                    }
                ]
            },
        )
        assert response.status_code == 422

    async def test_other_users_session_not_found(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        # Second user, inline (no client factory fixture exists).
        await authenticated_async_client.post(
            "/api/v1/users/register",
            json={
                "username": "other",
                "email": "other@example.com",
                "password": "otherpassword",
            },
        )
        await db.execute(
            update(User).where(User.email == "other@example.com").values(confirmed=True)
        )
        await db.commit()
        token = (
            await authenticated_async_client.post(
                "/api/v1/users/token",
                data={"username": "other@example.com", "password": "otherpassword"},
            )
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        response = await authenticated_async_client.get(
            f"{SESSIONS}/{session['id']}", headers=headers
        )
        assert response.status_code == 404
        response = await authenticated_async_client.post(
            f"{SESSIONS}/{session['id']}/stop", headers=headers
        )
        assert response.status_code == 404


class TestPauseResume:
    async def test_pause_resume_cycle(self, authenticated_async_client: AsyncClient) -> None:
        session = await _start(authenticated_async_client)
        sid = session["id"]
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/pause")
        assert r.status_code == 200
        assert r.json()["session"]["phases"][0]["status"] == "paused"
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/resume")
        assert r.status_code == 200
        assert r.json()["session"]["phases"][0]["status"] == "active"
        assert r.json()["session"]["phases"][0]["pause_count"] == 1

    async def test_pause_count_budget_abandons(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        session = await _start(authenticated_async_client, pause_budget_count=2)
        sid = session["id"]
        for _ in range(2):
            await authenticated_async_client.post(f"{SESSIONS}/{sid}/pause")
            await authenticated_async_client.post(f"{SESSIONS}/{sid}/resume")
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/pause")
        assert r.json()["session"]["status"] == "abandoned"
        profile = r.json()["profile"]
        assert profile["hp"] < profile["max_hp"]

    async def test_rapid_pause_cycle_emits_both_events(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """pause->resume->pause inside one second must not dedupe away the
        second pause (server eids differ via pause_count)."""
        session = await _start(authenticated_async_client)
        sid = session["id"]
        await authenticated_async_client.post(f"{SESSIONS}/{sid}/pause")
        await authenticated_async_client.post(f"{SESSIONS}/{sid}/resume")
        await authenticated_async_client.post(f"{SESSIONS}/{sid}/pause")
        events = await db.execute(
            select(GameEvent).where(GameEvent.type == "phase_paused")
        )
        assert len(events.scalars().all()) == 2

    async def test_pause_seconds_budget_abandons(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        sid = session["id"]
        await authenticated_async_client.post(f"{SESSIONS}/{sid}/pause")
        await db.execute(
            update(FocusPhase)
            .where(FocusPhase.session_id == sid, FocusPhase.seq == 0)
            .values(pause_started_at=_ago(400))
        )
        await db.commit()
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/resume")
        assert r.json()["session"]["status"] == "abandoned"
        events = await db.execute(select(GameEvent).where(GameEvent.type == "session_abandoned"))
        event = events.scalar_one()
        assert event.payload["reason"] == "pause_overflow"


class TestWallClockEvaluation:
    async def test_phase_auto_completes_and_break_starts(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        sid = session["id"]
        await _rewind_phase(db, sid, 10 * 60 + 10)
        r = await authenticated_async_client.get(f"{SESSIONS}/active")
        body = r.json()["session"]
        assert body["phases"][0]["status"] == "completed"
        assert body["phases"][1]["status"] == "active"  # break auto-started
        assert r.json()["profile"]["xp_today"] == 10  # 10 minutes, easy

    async def test_absent_session_auto_ends_after_grace(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Focus done -> break done -> next focus pending past grace = clean end."""
        session = await _start(authenticated_async_client)
        sid = session["id"]
        # Phase ends at t-25min; break ends t-20min; grace -> ended ~t-15min.
        await _rewind_phase(db, sid, 25 * 60)
        r = await authenticated_async_client.get(f"{SESSIONS}/active")
        assert r.status_code == 200
        body = r.json()
        if body is not None:
            assert body["session"]["status"] == "ended"
        else:
            # /active returns null once the session is no longer active —
            # fetch by id to confirm it ended cleanly.
            r2 = await authenticated_async_client.get(f"{SESSIONS}/{sid}")
            assert r2.json()["session"]["status"] == "ended"
            assert r2.json()["session"]["phases"][2]["status"] == "pending"

    async def test_completed_phase_pays_xp_and_gold(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client, difficulty="hard")
        sid = session["id"]
        await _rewind_phase(db, sid, 10 * 60 + 5)
        r = await authenticated_async_client.get(f"{SESSIONS}/active")
        profile = r.json()["profile"]
        assert profile["xp_today"] == 20  # 10min * hard(2.0)
        assert profile["gold_today"] > 0


class TestStop:
    async def test_manual_stop_mid_phase_costs_hp(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        session = await _start(authenticated_async_client)
        r = await authenticated_async_client.post(f"{SESSIONS}/{session['id']}/stop")
        body = r.json()
        assert body["session"]["status"] == "abandoned"
        assert body["profile"]["hp"] < body["profile"]["max_hp"]

    async def test_stop_after_completed_phase_is_clean(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        sid = session["id"]
        await _rewind_phase(db, sid, 10 * 60 + 5)
        # Trigger evaluation so phase 0 is completed + break running.
        await authenticated_async_client.get(f"{SESSIONS}/active")
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/stop")
        body = r.json()
        assert body["session"]["status"] == "ended"
        assert body["profile"]["hp"] == body["profile"]["max_hp"]

    async def test_restart_after_stop(self, authenticated_async_client: AsyncClient) -> None:
        session = await _start(authenticated_async_client)
        await authenticated_async_client.post(f"{SESSIONS}/{session['id']}/stop")
        session2 = await _start(authenticated_async_client)
        assert session2["status"] == "active"


class TestAdvance:
    async def test_advance_starts_pending_focus(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # auto_start_focus off -> post-break focus waits for a tap.
        session = await _start(authenticated_async_client)
        sid = session["id"]
        # Rewind BOTH clocks: session started 16m ago, phase 0 ended ~6m ago,
        # break ended ~1m ago -> focus pending, inside the 5m tap window.
        await db.execute(
            update(FocusSession).where(FocusSession.id == sid).values(started_at=_ago(16 * 60))
        )
        await _rewind_phase(db, sid, 16 * 60)
        await db.commit()
        await authenticated_async_client.get(f"{SESSIONS}/active")
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/advance")
        body = r.json()["session"]
        assert body["status"] == "active"
        assert body["phases"][2]["status"] == "active"

    async def test_advance_skips_break(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        sid = session["id"]
        await _rewind_phase(db, sid, 10 * 60 + 5)  # break just started
        await authenticated_async_client.get(f"{SESSIONS}/active")
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/advance")
        body = r.json()["session"]
        assert body["phases"][1]["status"] == "skipped"
        assert body["phases"][2]["status"] == "active"


class TestStopwatch:
    async def test_stopwatch_milestones_on_stop(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        r = await authenticated_async_client.post(SESSIONS, json={"mode": "stopwatch"})
        session = r.json()["session"]
        assert session["phases"][0]["kind"] == "stopwatch"
        await _rewind_phase(db, session["id"], 55 * 60)
        r = await authenticated_async_client.post(f"{SESSIONS}/{session['id']}/stop")
        body = r.json()
        assert body["session"]["status"] == "ended"
        assert body["profile"]["xp_today"] == 50  # 2 milestones (25, 50)
        events = await db.execute(select(GameEvent).where(GameEvent.type == "stopwatch_milestone"))
        assert len(events.scalars().all()) == 2
