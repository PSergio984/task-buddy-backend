"""API tests for the /api/v1/game event sync + profile endpoints."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import GameEvent, GameProfile
from app.models.user import User

GAME = "/api/v1/game"


def make_event(client_event_id: str, event_type: str, payload: dict, ts: datetime) -> dict:
    return {
        "client_event_id": client_event_id,
        "type": event_type,
        "client_ts": ts.isoformat(),
        "payload": payload,
    }


def focus_event(client_event_id: str, minutes: int = 25, ts: datetime | None = None) -> dict:
    return make_event(
        client_event_id,
        "focus_phase_completed",
        {"minutes": minutes, "difficulty": "easy"},
        ts or datetime.now(timezone.utc),
    )


class TestProfile:
    async def test_profile_autocreates(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        response = await authenticated_async_client.get(f"{GAME}/profile")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["level"] == 1
        assert body["xp"] == 0
        assert body["gold"] == 0
        assert body["hp"] == body["max_hp"]
        assert body["xp_to_next_level"] == 25

        result = await db.execute(select(GameProfile))
        assert result.scalar_one() is not None

    async def test_profile_requires_auth(self, async_client: AsyncClient) -> None:
        response = await async_client.get(f"{GAME}/profile")
        assert response.status_code == 401


class TestEventIngestion:
    async def test_focus_event_applies_scoring(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        response = await authenticated_async_client.post(
            f"{GAME}/events", json={"events": [focus_event("e-1")]}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["applied"] == 1
        assert body["duplicates"] == 0
        assert body["results"] == [{"client_event_id": "e-1", "status": "applied"}]
        # >= because a ~3% crit can legitimately multiply the award; xp_today
        # tracks total earned (level-ups reset in-level xp to the remainder).
        assert body["profile"]["xp_today"] >= 25
        assert body["profile"]["level"] >= 2
        assert body["profile"]["gold"] >= 5

    async def test_repost_is_idempotent(self, authenticated_async_client: AsyncClient) -> None:
        batch = {"events": [focus_event("e-1"), focus_event("e-2", minutes=10)]}
        first = await authenticated_async_client.post(f"{GAME}/events", json=batch)
        assert first.status_code == 200
        xp_after_first = first.json()["profile"]["xp"]
        gold_after_first = first.json()["profile"]["gold"]

        second = await authenticated_async_client.post(f"{GAME}/events", json=batch)
        assert second.status_code == 200
        body = second.json()
        assert body["applied"] == 0
        assert body["duplicates"] == 2
        assert body["profile"]["xp"] == xp_after_first
        assert body["profile"]["gold"] == gold_after_first

    async def test_mixed_batch_dedupes_only_seen(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        await authenticated_async_client.post(
            f"{GAME}/events", json={"events": [focus_event("e-1")]}
        )
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={"events": [focus_event("e-1"), focus_event("e-3", minutes=10)]},
        )
        statuses = {r["client_event_id"]: r["status"] for r in response.json()["results"]}
        assert statuses == {"e-1": "duplicate", "e-3": "applied"}

    async def test_duplicate_ids_within_one_batch(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={"events": [focus_event("e-1"), focus_event("e-1", minutes=10)]},
        )
        assert response.status_code == 200
        assert response.json()["applied"] == 1
        assert response.json()["duplicates"] == 1

    async def test_events_apply_in_client_ts_order(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        now = datetime.now(timezone.utc)
        # damage arrives first in the array but has the LATER client timestamp,
        # so the reward is applied first, then death zeroes level XP.
        batch = {
            "events": [
                make_event(
                    "e-kill",
                    "damage",
                    {"amount": 500},
                    now + timedelta(minutes=1),
                ),
                focus_event("e-reward", minutes=10, ts=now),
            ]
        }
        response = await authenticated_async_client.post(f"{GAME}/events", json=batch)
        assert response.status_code == 200
        assert response.json()["profile"]["xp"] == 0
        assert response.json()["profile"]["gold"] == 0

        # reversed timestamps: death first, then the reward lands on the fresh sheet
        batch2 = {
            "events": [
                focus_event("e-reward2", minutes=10, ts=now + timedelta(minutes=5)),
                make_event("e-kill2", "damage", {"amount": 500}, now),
            ]
        }
        response2 = await authenticated_async_client.post(f"{GAME}/events", json=batch2)
        assert response2.json()["profile"]["xp"] > 0

    async def test_damage_event_reduces_hp(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [make_event("d-1", "damage", {"amount": 4}, datetime.now(timezone.utc))]
            },
        )
        assert response.status_code == 200
        assert response.json()["profile"]["hp"] == pytest.approx(46.0)

    async def test_invalid_event_fails_batch(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    focus_event("e-1"),
                    focus_event("e-bad", minutes=-3),
                ]
            },
        )
        assert response.status_code == 400

        # transactional: nothing applied, nothing persisted
        profile = await authenticated_async_client.get(f"{GAME}/profile")
        assert profile.json()["xp"] == 0
        result = await authenticated_async_client.get(f"{GAME}/events")
        assert result.json()["events"] == []

    async def test_events_requires_auth(self, async_client: AsyncClient) -> None:
        response = await async_client.post(f"{GAME}/events", json={"events": [focus_event("e-1")]})
        assert response.status_code == 401

    async def test_empty_batch_rejected(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.post(f"{GAME}/events", json={"events": []})
        assert response.status_code == 422

    async def test_oversize_payload_rejected(self, authenticated_async_client: AsyncClient) -> None:
        # The ledger is per-user JSONB; a batch of fat payloads would grow it unbounded.
        event = focus_event("e-fat")
        event["payload"]["blob"] = "x" * (64 * 1024)
        response = await authenticated_async_client.post(f"{GAME}/events", json={"events": [event]})
        assert response.status_code == 422

    async def test_payload_cap_counts_utf8_bytes(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        # 6000 multibyte chars is ~18KB as bytes — must trip the byte cap.
        event = focus_event("e-utf8")
        event["payload"]["blob"] = "€" * 6000
        response = await authenticated_async_client.post(f"{GAME}/events", json={"events": [event]})
        assert response.status_code == 422

    async def test_non_finite_minutes_rejected(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        # JSON "1e999" parses to float inf server-side; engine must 400 not 500.
        body = (
            '{"events": [{"client_event_id": "e-inf", "type": "focus_phase_completed",'
            ' "client_ts": "2026-01-01T00:00:00Z", "payload": {"minutes": 1e999}}]}'
        )
        response = await authenticated_async_client.post(
            f"{GAME}/events", content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400

    async def test_outcome_namespaced_in_stored_payload(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # A client-supplied "applied" key must survive; the engine outcome is namespaced.
        event = focus_event("e-1")
        event["payload"]["applied"] = "client-owned"
        await authenticated_async_client.post(f"{GAME}/events", json={"events": [event]})
        result = await db.execute(select(GameEvent).where(GameEvent.client_event_id == "e-1"))
        stored = result.scalar_one().payload
        assert stored["applied"] == "client-owned"
        assert stored["_outcome"]["scored"] is True


class TestEventsFeed:
    async def test_events_since_filters(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        now = datetime.now(timezone.utc)
        batch = {
            "events": [
                focus_event("e-1", ts=now),
                focus_event("e-2", ts=now + timedelta(seconds=1)),
                focus_event("e-3", ts=now + timedelta(seconds=2)),
            ]
        }
        await authenticated_async_client.post(f"{GAME}/events", json=batch)

        all_events = await authenticated_async_client.get(f"{GAME}/events")
        assert len(all_events.json()["events"]) == 3

        # since = second event's id -> returns only events after it.
        # The id is the cursor: same-instant server_ts values can't disambiguate.
        result = await db.execute(select(GameEvent).where(GameEvent.client_event_id == "e-2"))
        second_id = result.scalar_one().id
        filtered = await authenticated_async_client.get(
            f"{GAME}/events", params={"since": second_id}
        )
        remaining = [e["client_event_id"] for e in filtered.json()["events"]]
        assert remaining == ["e-3"]

    async def test_events_scoped_to_user(
        self,
        authenticated_async_client: AsyncClient,
        async_client: AsyncClient,
        db: AsyncSession,
    ) -> None:
        await authenticated_async_client.post(
            f"{GAME}/events", json={"events": [focus_event("e-1")]}
        )

        # second user: register, confirm, log in
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

        events = await async_client.get(f"{GAME}/events", headers=headers)
        assert events.json()["events"] == []
        profile = await async_client.get(f"{GAME}/profile", headers=headers)
        assert profile.json()["level"] == 1
        assert profile.json()["xp"] == 0

    async def test_events_unauthenticated(self, async_client: AsyncClient) -> None:
        response = await async_client.get(f"{GAME}/events")
        assert response.status_code == 401
