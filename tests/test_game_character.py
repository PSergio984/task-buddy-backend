"""API tests for the character sheet: stat allocation, class, respec (#64)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import GameProfile

GAME = "/api/v1/game"
CHAR = "/api/v1/game/character"


async def _ensure_profile(client: AsyncClient) -> dict:
    """Create the profile row (first GET autocreates) and return its JSON."""
    response = await client.get(f"{GAME}/profile")
    assert response.status_code == 200, response.text
    return response.json()


async def _set_profile(db: AsyncSession, user_id: int, **fields) -> None:
    await db.execute(
        update(GameProfile).where(GameProfile.user_id == user_id).values(**fields)
    )
    await db.commit()


async def _profile_row(db: AsyncSession, user_id: int) -> GameProfile:
    result = await db.execute(select(GameProfile).where(GameProfile.user_id == user_id))
    return result.scalar_one()


class TestAllocate:
    async def test_allocate_spends_unspent_points(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], unspent_stat_points=5)

        response = await authenticated_async_client.post(
            f"{CHAR}/allocate", json={"points": {"str": 2, "int": 1}}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["str_stat"] == 2
        assert body["int_stat"] == 1
        assert body["unspent_stat_points"] == 2

        row = await _profile_row(db, confirmed_user["id"])
        assert row.str_stat == 2
        assert row.unspent_stat_points == 2

    async def test_allocate_rejects_overdraft(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], unspent_stat_points=1)

        response = await authenticated_async_client.post(
            f"{CHAR}/allocate", json={"points": {"str": 2}}
        )
        assert response.status_code == 400
        # Nothing applied atomically.
        row = await _profile_row(db, confirmed_user["id"])
        assert row.str_stat == 0
        assert row.unspent_stat_points == 1

    async def test_allocate_rejects_unknown_stat(
        self, authenticated_async_client: AsyncClient, confirmed_user: dict, db: AsyncSession
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], unspent_stat_points=5)
        response = await authenticated_async_client.post(
            f"{CHAR}/allocate", json={"points": {"agi": 1}}
        )
        assert response.status_code == 422

    async def test_allocate_rejects_stat_cap(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(
            db, confirmed_user["id"], unspent_stat_points=5, str_stat=100
        )
        response = await authenticated_async_client.post(
            f"{CHAR}/allocate", json={"points": {"str": 1}}
        )
        assert response.status_code == 400
        row = await _profile_row(db, confirmed_user["id"])
        assert row.str_stat == 100
        assert row.unspent_stat_points == 5

    async def test_allocate_rejects_empty_and_zero(
        self, authenticated_async_client: AsyncClient, confirmed_user: dict, db: AsyncSession
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], unspent_stat_points=5)
        assert (
            await authenticated_async_client.post(f"{CHAR}/allocate", json={"points": {}})
        ).status_code == 422
        assert (
            await authenticated_async_client.post(
                f"{CHAR}/allocate", json={"points": {"str": 0}}
            )
        ).status_code == 422

    async def test_allocate_requires_auth(self, async_client: AsyncClient) -> None:
        response = await async_client.post(f"{CHAR}/allocate", json={"points": {"str": 1}})
        assert response.status_code == 401


class TestAutoAllocate:
    async def test_enable_distributes_pool_evenly(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], unspent_stat_points=4)

        response = await authenticated_async_client.patch(
            f"{CHAR}", json={"auto_allocate": True}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["auto_allocate"] is True
        assert body["unspent_stat_points"] == 0
        # Classless distribution balances all four stats.
        assert (body["str_stat"], body["int_stat"], body["con_stat"], body["per_stat"]) == (
            1,
            1,
            1,
            1,
        )

    async def test_distribution_follows_class_affinity(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(
            db,
            confirmed_user["id"],
            unspent_stat_points=5,
            game_class="warrior",
        )
        response = await authenticated_async_client.patch(
            f"{CHAR}", json={"auto_allocate": True}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["unspent_stat_points"] == 0
        # Warrior affinity (str, con): alternating fill -> str 3, con 2.
        assert body["str_stat"] == 3
        assert body["con_stat"] == 2
        assert body["int_stat"] == 0
        assert body["per_stat"] == 0

    async def test_level_up_point_auto_distributes(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], auto_allocate=True)
        # Level 1 -> 25 XP = one level-up = one point.
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "e-lvl",
                        "type": "focus_phase_completed",
                        "client_ts": "2026-01-01T00:00:00Z",
                        "payload": {"minutes": 25, "difficulty": "easy"},
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        profile = response.json()["profile"]
        assert profile["level"] == 2
        assert profile["unspent_stat_points"] == 0
        allocated = (
            profile["str_stat"]
            + profile["int_stat"]
            + profile["con_stat"]
            + profile["per_stat"]
        )
        assert allocated == 1


class TestClassSelect:
    async def test_class_gated_below_level_10(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], level=9)
        response = await authenticated_async_client.post(
            f"{CHAR}/class", json={"game_class": "warrior"}
        )
        assert response.status_code == 400
        row = await _profile_row(db, confirmed_user["id"])
        assert row.game_class is None

    async def test_class_selects_at_level_10(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], level=10)
        response = await authenticated_async_client.post(
            f"{CHAR}/class", json={"game_class": "mage"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["game_class"] == "mage"

    async def test_second_pick_rejected_without_respec(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], level=10, game_class="mage")
        response = await authenticated_async_client.post(
            f"{CHAR}/class", json={"game_class": "rogue"}
        )
        assert response.status_code == 400

    async def test_unknown_class_rejected(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        response = await authenticated_async_client.post(
            f"{CHAR}/class", json={"game_class": "bard"}
        )
        assert response.status_code == 422


class TestRespec:
    async def test_respec_requires_class(
        self, authenticated_async_client: AsyncClient, confirmed_user: dict
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        response = await authenticated_async_client.post(f"{CHAR}/respec")
        assert response.status_code == 400

    async def test_respec_debits_gold_and_refunds_stats(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(
            db,
            confirmed_user["id"],
            level=10,
            game_class="mage",
            gold=200.0,
            str_stat=3,
            int_stat=2,
            unspent_stat_points=1,
        )
        response = await authenticated_async_client.post(f"{CHAR}/respec")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["gold"] == 100.0  # 200 - respec_gold_cost 100
        assert body["game_class"] is None
        assert body["unspent_stat_points"] == 6  # 1 + 3 + 2 refunded
        assert body["str_stat"] == 0
        assert body["int_stat"] == 0

    async def test_respec_requires_gold(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(
            db, confirmed_user["id"], level=10, game_class="mage", gold=50.0
        )
        response = await authenticated_async_client.post(f"{CHAR}/respec")
        assert response.status_code == 400

    async def test_respec_reopens_class_choice(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(
            db, confirmed_user["id"], level=10, game_class="mage", gold=200.0
        )
        assert (
            await authenticated_async_client.post(f"{CHAR}/respec")
        ).status_code == 200
        response = await authenticated_async_client.post(
            f"{CHAR}/class", json={"game_class": "rogue"}
        )
        assert response.status_code == 200
        assert response.json()["game_class"] == "rogue"
