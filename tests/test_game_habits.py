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

from app.crud import game as game_crud
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

    async def test_habit_cap_rejects_over_limit(
        self, authenticated_async_client: AsyncClient, db: AsyncSession, confirmed_user: dict
    ) -> None:
        # Seed the cap minus one directly; the cap-th via API works, the next 400s.
        db.add_all(
            [
                Habit(user_id=confirmed_user["id"], title=f"h{i}")
                for i in range(habit_service.MAX_HABITS_PER_USER - 1)
            ]
        )
        await db.commit()
        await _create(authenticated_async_client)  # reaches the cap — ok
        response = await authenticated_async_client.post(HABITS, json={"title": "one too many"})
        assert response.status_code == 400

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

    async def test_synced_click_direction_mismatch_records_unscored(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # The wedge scenario: queued while the habit accepted +, PATCHed to
        # negative-only before sync — the event lands unscored instead of
        # 400ing, and the rest of the batch still applies.
        habit = await _create(authenticated_async_client)
        bound = await _create(authenticated_async_client, title="bound", bind_focus=True)
        await authenticated_async_client.patch(
            f"{HABITS}/{habit['id']}", json={"direction": "negative"}
        )
        batch = {
            "events": [
                self._habit_event("h-1", {"habit_id": habit["id"], "direction": "positive"}),
                {
                    "client_event_id": "f-1",
                    "type": "focus_phase_completed",
                    "client_ts": datetime.now(timezone.utc).isoformat(),
                    "payload": {"minutes": 10, "difficulty": "easy"},
                },
            ]
        }
        response = await authenticated_async_client.post(f"{GAME}/events", json=batch)
        assert response.status_code == 200, response.text
        assert response.json()["applied"] == 2
        profile = response.json()["profile"]
        # 10 phase xp + 6 for the bound habit's auto-click; the mismatched
        # click scored nothing.
        assert profile["xp_today"] == 16

        result = await db.execute(select(GameEvent).where(GameEvent.client_event_id == "h-1"))
        outcome = result.scalar_one().payload["_outcome"]
        assert outcome == {"scored": False, "reason": "direction_mismatch"}
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 0
        assert row.value == pytest.approx(0.0)

        # The scored phase in the same batch still fans out to bound habits.
        bound_row = await _get_habit_row(db, bound["id"])
        assert bound_row.counter == 1

        # An unscored eid is still consumed — replay dedupes; a corrected
        # click must resend under a NEW client_event_id.
        replay = await authenticated_async_client.post(f"{GAME}/events", json=batch)
        assert replay.json()["duplicates"] == 2

    async def test_forged_marker_keys_stripped_from_stored_rows(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # Reserved server markers in a client payload never reach the ledger
        # row; legit extras pass through untouched.
        habit = await _create(authenticated_async_client)
        await _create(authenticated_async_client, title="bound", bind_focus=True)
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    self._habit_event(
                        "h-1",
                        {
                            "habit_id": habit["id"],
                            "direction": "positive",
                            "auto": True,
                            "session_id": 5,
                            "note": "legit",
                        },
                    ),
                    {
                        "client_event_id": "f-1",
                        "type": "focus_phase_completed",
                        "client_ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {"minutes": 10, "auto": True, "session_id": 5},
                    },
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["applied"] == 2
        h1 = (
            await db.execute(select(GameEvent).where(GameEvent.client_event_id == "h-1"))
        ).scalar_one()
        assert h1.payload["note"] == "legit"
        assert "auto" not in h1.payload
        assert "session_id" not in h1.payload
        f1 = (
            await db.execute(select(GameEvent).where(GameEvent.client_event_id == "f-1"))
        ).scalar_one()
        assert f1.payload["minutes"] == 10
        assert "auto" not in f1.payload
        assert "session_id" not in f1.payload
        # ...while the phase's genuine auto-click row still stamps its marker.
        auto_rows = (
            (await db.execute(select(GameEvent).where(GameEvent.client_event_id.like("server:%"))))
            .scalars()
            .all()
        )
        assert [r.payload["auto"] for r in auto_rows] == [True]

    @pytest.mark.parametrize("bad_id", [999999, "not-an-id", True])
    async def test_unresolvable_habit_event_records_unscored(
        self, authenticated_async_client: AsyncClient, bad_id: object
    ) -> None:
        # No owned habit row (missing/foreign/malformed id): the event lands
        # unscored — claimed value/difficulty can't amplify rewards.
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    self._habit_event(
                        "h-1",
                        {
                            "habit_id": bad_id,
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
        profile = response.json()["profile"]
        assert profile["xp_today"] == 0
        assert profile["gold_today"] == 0
        assert profile["hp"] == profile["max_hp"]

    async def test_deleted_habit_event_records_unscored(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # Click queued before the delete; habit gone by sync time.
        habit = await _create(authenticated_async_client)
        await authenticated_async_client.delete(f"{HABITS}/{habit['id']}")
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    self._habit_event("h-1", {"habit_id": habit["id"], "direction": "positive"})
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["applied"] == 1
        result = await db.execute(select(GameEvent).where(GameEvent.client_event_id == "h-1"))
        assert result.scalar_one().payload["_outcome"] == {
            "scored": False,
            "reason": "habit_unresolvable",
        }

    async def test_two_synced_clicks_drift_sequentially(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # Both clicks in one batch must each see the freshest stored value —
        # second click drifts from the first's write-back, not a stale read.
        habit = await _create(authenticated_async_client)
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    self._habit_event("h-1", {"habit_id": habit["id"], "direction": "positive"}),
                    self._habit_event("h-2", {"habit_id": habit["id"], "direction": "positive"}),
                ]
            },
        )
        assert response.status_code == 200, response.text
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 2
        assert row.value == pytest.approx(1.0 + 0.9747**1.0, abs=1e-6)

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

    async def test_multiple_bound_habits_each_auto_click(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        bound_a = await _create(authenticated_async_client, title="a", bind_focus=True)
        bound_b = await _create(authenticated_async_client, title="b", bind_focus=True)
        unbound = await _create(authenticated_async_client, title="c")
        session = await self._start_session(authenticated_async_client)
        await db.execute(
            update(FocusPhase)
            .where(FocusPhase.session_id == session["id"], FocusPhase.seq == 0)
            .values(started_at=_ago(10 * 60 + 5))
        )
        await db.commit()
        await authenticated_async_client.get(f"{SESSIONS}/active")
        for habit_id in (bound_a["id"], bound_b["id"]):
            row = await _get_habit_row(db, habit_id)
            assert row.counter == 1
            assert row.value == pytest.approx(1.0)
        row = await _get_habit_row(db, unbound["id"])
        assert row.counter == 0

    async def test_stopwatch_does_not_auto_click(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # Spec is literal: binding fires per focus_phase_completed — a
        # stopwatch session scores milestones, never a phase completion.
        habit = await _create(authenticated_async_client, bind_focus=True)
        response = await authenticated_async_client.post(SESSIONS, json={"mode": "stopwatch"})
        assert response.status_code == 201, response.text
        session = response.json()["session"]
        await db.execute(
            update(FocusPhase)
            .where(FocusPhase.session_id == session["id"], FocusPhase.seq == 0)
            .values(started_at=_ago(30 * 60))
        )
        await db.commit()
        await authenticated_async_client.post(f"{SESSIONS}/{session['id']}/stop")
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 0
        assert row.value == pytest.approx(0.0)

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

    async def test_auto_click_budget_bounds_fanout(
        self,
        authenticated_async_client: AsyncClient,
        db: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # shortcut (habit_service): fanout is per-phase-per-bound-habit, but
        # the per-evaluation budget caps abuse-scale claimed batches.
        monkeypatch.setattr(habit_service, "MAX_AUTO_CLICKS_PER_EVAL", 3)
        bound_a = await _create(authenticated_async_client, title="a", bind_focus=True)
        bound_b = await _create(authenticated_async_client, title="b", bind_focus=True)
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": f"f-{i}",
                        "type": "focus_phase_completed",
                        "client_ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {"minutes": 10, "difficulty": "easy"},
                    }
                    for i in range(3)
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["applied"] == 3
        # All three phases scored; only the budget's share of fanout wrote.
        assert response.json()["profile"]["xp_today"] >= 30
        result = await db.execute(select(GameEvent).where(GameEvent.type == "habit_click"))
        assert len(result.scalars().all()) == 3
        # Candidates fire in id order until the budget runs out.
        assert (await _get_habit_row(db, bound_a["id"])).counter == 2
        assert (await _get_habit_row(db, bound_b["id"])).counter == 1

    async def test_multi_phase_catchup_fetches_bound_habits_once(
        self,
        authenticated_async_client: AsyncClient,
        db: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        habit = await _create(authenticated_async_client, bind_focus=True)
        session = await self._start_session(
            authenticated_async_client,
            auto_start_focus=True,  # chain both focus phases in one catch-up
            phases=[
                {"kind": "focus", "minutes": 10},
                {"kind": "break", "minutes": 5},
                {"kind": "focus", "minutes": 10},
            ],
        )
        await db.execute(
            update(FocusPhase)
            .where(FocusPhase.session_id == session["id"], FocusPhase.seq == 0)
            .values(started_at=_ago(26 * 60))
        )
        await db.commit()
        calls = 0
        original = game_crud.list_habits

        async def counting(db_: AsyncSession, user_id_: int) -> list[Habit]:
            nonlocal calls
            calls += 1
            return await original(db_, user_id_)

        monkeypatch.setattr(game_crud, "list_habits", counting)
        await authenticated_async_client.get(f"{SESSIONS}/active")
        row = await _get_habit_row(db, habit["id"])
        assert row.counter == 2  # both focus phases auto-clicked
        assert calls == 1  # one bound-habit fetch served the whole evaluation
