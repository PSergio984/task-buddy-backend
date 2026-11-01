"""API tests for /api/v1/game/habits — CRUD, click scoring, drift, focus binding.

Drift numbers assume GameRates defaults: delta = 0.9747**value, XP =
delta * P * INT-bonus * crit * 6, gold = ceil(delta * P * crit * PER-bonus),
-value HP = delta * P * 2 * CON-shield (floor). RNG is seeded so no crit fires.
"""

import random
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.game import habit_service, service, session_service
from app.models.game import FocusPhase, GameEvent, Habit
from app.models.user import User

GAME = "/api/v1/game"
HABITS = f"{GAME}/habits"
SESSIONS = f"{GAME}/sessions"


@pytest.fixture(autouse=True)
def _seeded_rng(monkeypatch) -> None:
    """Deterministic crit rolls: seed 0's early draws stay above crit chance."""
    monkeypatch.setattr(service, "_rng", random.Random(0))
    monkeypatch.setattr(habit_service, "_rng", random.Random(0))
    monkeypatch.setattr(session_service, "_rng", random.Random(0))


def _ago(seconds: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


async def _create(client: AsyncClient, **overrides) -> dict:
    body = {"title": "Meditate", **overrides}
    response = await client.post(HABITS, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _click(client: AsyncClient, habit_id: int, direction: str, **extra) -> dict:
    response = await client.post(
        f"{HABITS}/{habit_id}/click", json={"direction": direction, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _get_habit_row(db: AsyncSession, habit_id: int) -> Habit:
    result = await db.execute(select(Habit).where(Habit.id == habit_id))
    return result.scalar_one()


async def _seed_value(db: AsyncSession, habit_id: int, value: float) -> None:
    await db.execute(update(Habit).where(Habit.id == habit_id).values(value=value))
    await db.commit()


class TestHabitCrud:
    async def test_create_defaults(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client)
        assert habit["title"] == "Meditate"
        assert habit["direction"] == "both"
        assert habit["difficulty"] == "easy"
        assert habit["value"] == 0
        assert habit["counter"] == 0
        assert habit["bind_focus"] is False
        assert habit["reminder_times"] == []

    async def test_create_full_fields(self, authenticated_async_client: AsyncClient) -> None:
        habit = await _create(
            authenticated_async_client,
            title="Read",
            notes="30 pages",
            direction="positive",
            difficulty="hard",
            reminder_times=["08:00", "21:30"],
            bind_focus=True,
        )
        assert habit["direction"] == "positive"
        assert habit["difficulty"] == "hard"
        assert habit["reminder_times"] == ["08:00", "21:30"]
        assert habit["bind_focus"] is True
        assert habit["notes"] == "30 pages"

    async def test_create_blank_title_rejected(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        response = await authenticated_async_client.post(HABITS, json={"title": "   "})
        assert response.status_code == 422

    async def test_create_bad_reminder_time_rejected(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        for bad in ("8:00", "25:00", "12:60", "noon", 8):
            response = await authenticated_async_client.post(
                HABITS, json={"title": "x", "reminder_times": [bad]}
            )
            assert response.status_code == 422, bad

    async def test_create_invalid_direction_rejected(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        response = await authenticated_async_client.post(
            HABITS, json={"title": "x", "direction": "sideways"}
        )
        assert response.status_code == 422

    async def test_list_returns_own_habits_only(
        self,
        authenticated_async_client: AsyncClient,
        async_client: AsyncClient,
        db: AsyncSession,
    ) -> None:
        await _create(authenticated_async_client, title="Mine")
        response = await authenticated_async_client.get(HABITS)
        assert [h["title"] for h in response.json()] == ["Mine"]

        # second user's list stays empty
        await async_client.post(
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
        login = await async_client.post(
            "/api/v1/users/token",
            data={"username": "other@example.com", "password": "otherpassword"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = await async_client.get(HABITS, headers=headers)
        assert response.json() == []

    async def test_get_one(self, authenticated_async_client: AsyncClient) -> None:
        habit = await _create(authenticated_async_client)
        response = await authenticated_async_client.get(f"{HABITS}/{habit['id']}")
        assert response.status_code == 200
        assert response.json()["title"] == "Meditate"

    async def test_get_other_users_habit_not_found(
        self,
        authenticated_async_client: AsyncClient,
        async_client: AsyncClient,
        db: AsyncSession,
    ) -> None:
        habit = await _create(authenticated_async_client)
        await async_client.post(
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
        login = await async_client.post(
            "/api/v1/users/token",
            data={"username": "other@example.com", "password": "otherpassword"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = await async_client.get(f"{HABITS}/{habit['id']}", headers=headers)
        assert response.status_code == 404

    async def test_patch_updates_fields(self, authenticated_async_client: AsyncClient) -> None:
        habit = await _create(authenticated_async_client)
        response = await authenticated_async_client.patch(
            f"{HABITS}/{habit['id']}",
            json={"title": "Meditate more", "direction": "positive", "bind_focus": True},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == "Meditate more"
        assert body["direction"] == "positive"
        assert body["bind_focus"] is True

    async def test_patch_cannot_touch_drift_state(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # value/counter are engine-owned — not updatable through the API.
        habit = await _create(authenticated_async_client)
        response = await authenticated_async_client.patch(
            f"{HABITS}/{habit['id']}", json={"value": 21.0, "counter": 99}
        )
        assert response.status_code == 400
        row = await _get_habit_row(db, habit["id"])
        assert row.value == 0
        assert row.counter == 0

    async def test_patch_null_required_field_rejected(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        # An explicit null would write NULL into a non-nullable column.
        habit = await _create(authenticated_async_client)
        response = await authenticated_async_client.patch(
            f"{HABITS}/{habit['id']}", json={"direction": None}
        )
        assert response.status_code == 422

    async def test_patch_empty_rejected(self, authenticated_async_client: AsyncClient) -> None:
        habit = await _create(authenticated_async_client)
        response = await authenticated_async_client.patch(f"{HABITS}/{habit['id']}", json={})
        assert response.status_code == 400

    async def test_patch_not_found(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.patch(f"{HABITS}/999999", json={"title": "x"})
        assert response.status_code == 404

    async def test_delete(self, authenticated_async_client: AsyncClient) -> None:
        habit = await _create(authenticated_async_client)
        response = await authenticated_async_client.delete(f"{HABITS}/{habit['id']}")
        assert response.status_code == 200
        followup = await authenticated_async_client.get(f"{HABITS}/{habit['id']}")
        assert followup.status_code == 404

    async def test_delete_not_found(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.delete(f"{HABITS}/999999")
        assert response.status_code == 404

    async def test_requires_auth(self, async_client: AsyncClient) -> None:
        assert (await async_client.get(HABITS)).status_code == 401
        assert (await async_client.post(HABITS, json={"title": "x"})).status_code == 401


class TestHabitClick:
    async def test_positive_click_pays_xp_gold_and_drifts(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client)
        body = await _click(authenticated_async_client, habit["id"], "positive")
        assert body["status"] == "applied"
        # delta = 0.9747**0 = 1 -> xp = round(1 * 6) = 6, gold = ceil(1) = 1
        assert body["profile"]["xp_today"] == 6
        assert body["profile"]["gold_today"] == 1
        assert body["profile"]["hp"] == body["profile"]["max_hp"]
        assert body["habit"]["counter"] == 1
        assert body["habit"]["value"] == pytest.approx(1.0)

        result = await db.execute(select(GameEvent).where(GameEvent.type == "habit_click"))
        event = result.scalar_one()
        assert event.payload["habit_id"] == habit["id"]
        assert event.payload["direction"] == "positive"
        assert event.payload["value"] == pytest.approx(0.0)  # value before
        assert event.payload["_outcome"]["new_value"] == pytest.approx(1.0)

    async def test_negative_click_costs_hp_only(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        habit = await _create(authenticated_async_client, direction="negative")
        body = await _click(authenticated_async_client, habit["id"], "negative")
        profile = body["profile"]
        assert profile["hp"] == pytest.approx(profile["max_hp"] - 2)
        assert profile["xp_today"] == 0
        assert profile["gold_today"] == 0
        assert body["habit"]["counter"] == -1
        assert body["habit"]["value"] == pytest.approx(-1.0)

    async def test_positive_click_rejected_on_negative_habit(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        habit = await _create(authenticated_async_client, direction="negative")
        response = await authenticated_async_client.post(
            f"{HABITS}/{habit['id']}/click", json={"direction": "positive"}
        )
        assert response.status_code == 400

    async def test_negative_click_rejected_on_positive_habit(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        habit = await _create(authenticated_async_client, direction="positive")
        response = await authenticated_async_client.post(
            f"{HABITS}/{habit['id']}/click", json={"direction": "negative"}
        )
        assert response.status_code == 400

    async def test_click_not_found(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.post(
            f"{HABITS}/999999/click", json={"direction": "positive"}
        )
        assert response.status_code == 404

    async def test_click_idempotent_on_client_event_id(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        habit = await _create(authenticated_async_client)
        first = await _click(
            authenticated_async_client, habit["id"], "positive", client_event_id="c-1"
        )
        assert first["status"] == "applied"
        second = await _click(
            authenticated_async_client, habit["id"], "positive", client_event_id="c-1"
        )
        assert second["status"] == "duplicate"
        # No second click: counter and drift stay where the first left them.
        assert second["habit"]["counter"] == 1
        assert second["habit"]["value"] == pytest.approx(1.0)

    async def test_click_then_batch_replay_dedupes(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # A client that clicked via the endpoint and later syncs the same
        # queued event must not double-score.
        habit = await _create(authenticated_async_client)
        await _click(authenticated_async_client, habit["id"], "positive", client_event_id="c-1")
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "c-1",
                        "type": "habit_click",
                        "client_ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {"habit_id": habit["id"], "direction": "positive"},
                    }
                ]
            },
        )
        assert response.json()["duplicates"] == 1
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 1


class TestDriftBounds:
    async def test_neglected_habit_pays_more(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client)
        await _seed_value(db, habit["id"], -47.27)  # clamp floor
        body = await _click(authenticated_async_client, habit["id"], "positive")
        # delta = 0.9747**-47.27 ~= 3.36 -> xp = round(3.36*6) = 20 > 6
        assert body["profile"]["xp_today"] > 6
        row = await _get_habit_row(db, habit["id"])
        assert row.value > -47.27

    async def test_farmed_habit_pays_less(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client)
        await _seed_value(db, habit["id"], 10.0)
        body = await _click(authenticated_async_client, habit["id"], "positive")
        assert body["profile"]["xp_today"] < 6

    async def test_value_clamps_at_max(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client)
        await _seed_value(db, habit["id"], 21.27)  # clamp ceiling
        body = await _click(authenticated_async_client, habit["id"], "positive")
        assert body["habit"]["value"] == pytest.approx(21.27)

    async def test_value_clamps_at_min(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client)
        await _seed_value(db, habit["id"], -47.27)
        body = await _click(authenticated_async_client, habit["id"], "negative")
        assert body["habit"]["value"] == pytest.approx(-47.27)

    async def test_drift_accumulates_per_click(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        # +clicks push value up, shrinking each subsequent reward.
        habit = await _create(authenticated_async_client)
        await _click(authenticated_async_client, habit["id"], "positive")
        second = await _click(authenticated_async_client, habit["id"], "positive")
        assert second["habit"]["value"] == pytest.approx(1.0 + 0.9747**1.0, abs=1e-6)
        assert second["habit"]["counter"] == 2


class TestHabitEventSync:
    """Offline-queued habit_click events resolve the stored habit state."""

    def _habit_event(self, eid: str, payload: dict) -> dict:
        return {
            "client_event_id": eid,
            "type": "habit_click",
            "client_ts": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }

    async def test_synced_click_uses_stored_value_and_writes_drift(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client)
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    self._habit_event(
                        "h-1",
                        # Client claims max drift + hard difficulty — the
                        # stored row (value 0, easy) wins both.
                        {
                            "habit_id": habit["id"],
                            "direction": "positive",
                            "value": 21.27,
                            "difficulty": "hard",
                        },
                    )
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["applied"] == 1
        row = await _get_habit_row(db, habit["id"])
        assert row.value == pytest.approx(1.0)
        assert row.counter == 1
        # Stored payload records the authoritative fields, not the claim.
        result = await db.execute(select(GameEvent).where(GameEvent.client_event_id == "h-1"))
        stored = result.scalar_one().payload
        assert stored["value"] == pytest.approx(0.0)
        assert stored["difficulty"] == "easy"

    async def test_synced_click_respects_direction(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        habit = await _create(authenticated_async_client, direction="negative")
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    self._habit_event("h-1", {"habit_id": habit["id"], "direction": "positive"})
                ]
            },
        )
        assert response.status_code == 400

    async def test_synced_click_on_missing_habit_still_applies(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        # Habit deleted between queue and sync: the ledger event can't drift a
        # row, so it scores on the client-claimed value (pre-#62 contract).
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    self._habit_event(
                        "h-1", {"habit_id": 999999, "direction": "positive", "value": 0.0}
                    )
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["applied"] == 1

    async def test_synced_click_replay_dedupes(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client)
        batch = {
            "events": [self._habit_event("h-1", {"habit_id": habit["id"], "direction": "positive"})]
        }
        await authenticated_async_client.post(f"{GAME}/events", json=batch)
        second = await authenticated_async_client.post(f"{GAME}/events", json=batch)
        assert second.json()["duplicates"] == 1
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 1  # replayed batch did not re-drift


class TestFocusBinding:
    async def _start_session(self, client: AsyncClient, **overrides) -> dict:
        body = {
            "mode": "timer",
            "phases": [{"kind": "focus", "minutes": 10}, {"kind": "break", "minutes": 5}],
            **overrides,
        }
        response = await client.post(SESSIONS, json=body)
        assert response.status_code == 201, response.text
        return response.json()["session"]

    async def test_bound_habit_auto_clicks_on_phase_completion(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client, bind_focus=True)
        session = await self._start_session(authenticated_async_client)
        await db.execute(
            update(FocusPhase)
            .where(FocusPhase.session_id == session["id"], FocusPhase.seq == 0)
            .values(started_at=_ago(10 * 60 + 5))
        )
        await db.commit()
        response = await authenticated_async_client.get(f"{SESSIONS}/active")
        assert response.json()["session"]["phases"][0]["status"] == "completed"

        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 1
        assert row.value == pytest.approx(1.0)
        result = await db.execute(select(GameEvent).where(GameEvent.type == "habit_click"))
        event = result.scalar_one()
        assert event.client_event_id.startswith("server:")
        assert event.payload["habit_id"] == habit["id"]
        assert event.payload["auto"] is True

    async def test_unbound_habit_not_auto_clicked(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client)  # bind_focus off
        session = await self._start_session(authenticated_async_client)
        await db.execute(
            update(FocusPhase)
            .where(FocusPhase.session_id == session["id"], FocusPhase.seq == 0)
            .values(started_at=_ago(10 * 60 + 5))
        )
        await db.commit()
        await authenticated_async_client.get(f"{SESSIONS}/active")
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 0
        assert row.value == pytest.approx(0.0)

    async def test_negative_only_bound_habit_not_auto_clicked(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # Auto-click is always a +click; a negative-only habit can't accept it.
        habit = await _create(authenticated_async_client, direction="negative", bind_focus=True)
        session = await self._start_session(authenticated_async_client)
        await db.execute(
            update(FocusPhase)
            .where(FocusPhase.session_id == session["id"], FocusPhase.seq == 0)
            .values(started_at=_ago(10 * 60 + 5))
        )
        await db.commit()
        await authenticated_async_client.get(f"{SESSIONS}/active")
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 0

    async def test_auto_click_fires_once_per_phase(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        habit = await _create(authenticated_async_client, bind_focus=True)
        session = await self._start_session(authenticated_async_client)
        await db.execute(
            update(FocusPhase)
            .where(FocusPhase.session_id == session["id"], FocusPhase.seq == 0)
            .values(started_at=_ago(10 * 60 + 5))
        )
        await db.commit()
        await authenticated_async_client.get(f"{SESSIONS}/active")
        # Re-evaluation persists no new steps -> no second auto-click.
        await authenticated_async_client.get(f"{SESSIONS}/active")
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 1

    async def test_offline_focus_phase_auto_clicks(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # A client-run session synced through /events triggers the same
        # binding — the offline contract treats it as a real phase completion.
        habit = await _create(authenticated_async_client, bind_focus=True)
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "f-1",
                        "type": "focus_phase_completed",
                        "client_ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {"minutes": 25, "difficulty": "easy"},
                    }
                ]
            },
        )
        assert response.status_code == 200
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 1
        assert row.value == pytest.approx(1.0)

        # Replaying the same phase event does not auto-click again.
        await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "f-1",
                        "type": "focus_phase_completed",
                        "client_ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {"minutes": 25, "difficulty": "easy"},
                    }
                ]
            },
        )
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 1
