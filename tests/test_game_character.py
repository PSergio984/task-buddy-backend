"""API tests for the character sheet: stat allocation, class, respec (#64)."""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import Daily, DailyCheck, GameEvent, GameProfile, UserAchievement

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


# --- Gear (issue #64) ---------------------------------------------------------

GEAR = "/api/v1/game/gear"


async def _gear(client: AsyncClient) -> dict[str, dict]:
    """Catalog keyed by item key after one seeded GET."""
    response = await client.get(GEAR)
    assert response.status_code == 200, response.text
    return {row["key"]: row for row in response.json()}


async def _buy(client: AsyncClient, key: str) -> dict:
    response = await client.post(f"{GEAR}/buy", json={"key": key})
    assert response.status_code == 200, response.text
    return {row["key"]: row for row in response.json()}[key]


class TestGearCatalog:
    async def test_catalog_seeds_and_covers_slots(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        items = await _gear(authenticated_async_client)
        assert len(items) == 24
        # All four class ladders present plus all-class fillers.
        klasses = {row["klass"] for row in items.values()}
        assert klasses == {"warrior", "mage", "healer", "rogue", "all"}
        # Every one of the seven slots is fillable for any class.
        warrior_slots = {r["slot"] for r in items.values() if r["klass"] in ("warrior", "all")}
        assert warrior_slots == {
            "weapon", "shield", "head", "armor", "body", "back", "eyewear"
        }

    async def test_catalog_is_idempotent(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        first = await _gear(authenticated_async_client)
        second = await _gear(authenticated_async_client)
        assert [r["key"] for r in second.values()] == [r["key"] for r in first.values()]


class TestGearBuy:
    async def test_buy_debits_gold_and_marks_owned(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], gold=150.0)
        item = await _buy(authenticated_async_client, "all-shield-1")
        assert item["owned"] is True
        assert item["equipped"] is False
        row = await _profile_row(db, confirmed_user["id"])
        # 150 - 50 cost + 10 first-gear badge.
        assert row.gold == pytest.approx(110.0)

    async def test_buy_rejects_insufficient_gold(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], gold=10.0)
        response = await authenticated_async_client.post(
            f"{GEAR}/buy", json={"key": "all-shield-1"}
        )
        assert response.status_code == 400
        row = await _profile_row(db, confirmed_user["id"])
        assert row.gold == pytest.approx(10.0)

    async def test_buy_rejects_duplicate(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], gold=500.0)
        await _buy(authenticated_async_client, "all-shield-1")
        response = await authenticated_async_client.post(
            f"{GEAR}/buy", json={"key": "all-shield-1"}
        )
        assert response.status_code == 400

    async def test_buy_rejects_wrong_class(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(
            db, confirmed_user["id"], level=10, game_class="mage", gold=500.0
        )
        response = await authenticated_async_client.post(
            f"{GEAR}/buy", json={"key": "warrior-weapon-1"}
        )
        assert response.status_code == 400
        # Classless users can't buy class-locked pieces either.
        await _set_profile(db, confirmed_user["id"], game_class=None)
        response = await authenticated_async_client.post(
            f"{GEAR}/buy", json={"key": "warrior-weapon-1"}
        )
        assert response.status_code == 400

    async def test_buy_enforces_ladder_order(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(
            db, confirmed_user["id"], level=10, game_class="warrior", gold=500.0
        )
        response = await authenticated_async_client.post(
            f"{GEAR}/buy", json={"key": "warrior-weapon-2"}
        )
        assert response.status_code == 400
        await _buy(authenticated_async_client, "warrior-weapon-1")
        item = await _buy(authenticated_async_client, "warrior-weapon-2")
        assert item["owned"] is True

    async def test_buy_unknown_key_404(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        response = await authenticated_async_client.post(
            f"{GEAR}/buy", json={"key": "mystery-sword"}
        )
        assert response.status_code == 404


class TestGearEquip:
    async def _setup_warrior(
        self, client: AsyncClient, db: AsyncSession, user_id: int
    ) -> None:
        await _ensure_profile(client)
        await _set_profile(db, user_id, level=10, game_class="warrior", gold=600.0)
        await _buy(client, "warrior-weapon-1")
        await _buy(client, "all-shield-1")

    async def test_equip_and_unequip(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        response = await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "warrior-weapon-1", "equipped": True}
        )
        assert response.status_code == 200, response.text
        items = {r["key"]: r for r in response.json()}
        assert items["warrior-weapon-1"]["equipped"] is True
        response = await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "warrior-weapon-1", "equipped": False}
        )
        items = {r["key"]: r for r in response.json()}
        assert items["warrior-weapon-1"]["equipped"] is False

    async def test_equip_bumps_same_slot(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        await _buy(authenticated_async_client, "warrior-weapon-2")
        await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "warrior-weapon-1"}
        )
        response = await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "warrior-weapon-2"}
        )
        items = {r["key"]: r for r in response.json()}
        # One per slot: the tier-1 sword yields to the tier-2.
        assert items["warrior-weapon-2"]["equipped"] is True
        assert items["warrior-weapon-1"]["equipped"] is False

    async def test_equip_rejects_unowned(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        response = await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "warrior-armor-1"}
        )
        assert response.status_code == 400

    async def test_respec_unequips_class_locked_pieces(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "warrior-weapon-1"}
        )
        await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "all-shield-1"}
        )
        response = await authenticated_async_client.post(f"{CHAR}/respec")
        assert response.status_code == 200, response.text
        items = await _gear(authenticated_async_client)
        # Class piece stripped; the 'all' shield stays worn.
        assert items["warrior-weapon-1"]["equipped"] is False
        assert items["all-shield-1"]["equipped"] is True


class TestGearScoring:
    async def test_equipped_int_boosts_xp(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """Equipped stats feed scoring: mage weapon INT raises XP earned."""
        await _ensure_profile(authenticated_async_client)
        await _set_profile(
            db, confirmed_user["id"], level=10, game_class="mage", gold=200.0
        )
        await _buy(authenticated_async_client, "mage-weapon-1")  # int +3
        await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "mage-weapon-1"}
        )
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "e-xp",
                        "type": "focus_phase_completed",
                        "client_ts": "2026-01-01T00:00:00Z",
                        "payload": {"minutes": 10, "difficulty": "easy"},
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        # xp = round(10 * 1 * 1 * (1 + 0.025*3) * 1) = 11 — gear INT counts.
        assert response.json()["profile"]["xp"] == 11

    async def test_equipped_con_reduces_miss_damage(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], gold=150.0, hp=50.0)
        await _buy(authenticated_async_client, "all-shield-1")  # con +1
        await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "all-shield-1"}
        )
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "e-dmg",
                        "type": "damage",
                        "client_ts": "2026-01-01T00:00:00Z",
                        "payload": {"amount": 4},
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        # shield = 1 - 1/250 -> floor(4 * 0.996) = 3 lost.
        assert response.json()["profile"]["hp"] == pytest.approx(47.0)


# --- Achievements (issue #64) --------------------------------------------------

BADGES = "/api/v1/game/achievements"


async def _badges(client: AsyncClient) -> dict[str, dict]:
    response = await client.get(BADGES)
    assert response.status_code == 200, response.text
    return {row["key"]: row for row in response.json()}


async def _score_event(client: AsyncClient, eid: str) -> dict:
    """One 10-min focus phase through ingest — triggers post-score eval."""
    response = await client.post(
        f"{GAME}/events",
        json={
            "events": [
                {
                    "client_event_id": eid,
                    "type": "focus_phase_completed",
                    "client_ts": "2026-01-01T00:00:00Z",
                    "payload": {"minutes": 10, "difficulty": "easy"},
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["profile"]


class TestAchievements:
    async def test_registry_seeds_15_badges(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        badges = await _badges(authenticated_async_client)
        assert len(badges) == 15
        assert {
            "level-10", "level-25", "level-50",
            "first-focus", "first-habit", "first-daily", "first-gear",
            "class-picked", "focus-100", "focus-1000", "marathon",
            "streak-7", "streak-21", "perfect-day", "clicker-50",
        } == set(badges)
        assert all(row["earned_at"] is None for row in badges.values())

    async def test_scored_event_grants_first_focus(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        profile = await _score_event(authenticated_async_client, "e-ach-1")
        # Badge gold lands on the same profile read.
        assert profile["gold"] == pytest.approx(12.0)  # 2 phase + 10 badge
        badges = await _badges(authenticated_async_client)
        assert badges["first-focus"]["earned_at"] is not None
        assert badges["focus-100"]["earned_at"] is None  # 10 < 100 minutes

    async def test_grants_are_idempotent(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _score_event(authenticated_async_client, "e-ach-2a")
        await _score_event(authenticated_async_client, "e-ach-2b")
        row = await _profile_row(db, confirmed_user["id"])
        # Two scored phases (4 gold) + ONE first-focus reward (10) — no dup.
        assert row.gold == pytest.approx(14.0)
        result = await db.execute(
            select(func.count())
            .select_from(UserAchievement)
            .where(UserAchievement.user_id == confirmed_user["id"])
        )
        assert result.scalar_one() == 1

    async def test_level_tier_grants(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], level=10)
        profile = await _score_event(authenticated_async_client, "e-ach-3")
        assert profile["gold"] == pytest.approx(10 * 0.2 * 1 + 10 + 25)
        badges = await _badges(authenticated_async_client)
        assert badges["level-10"]["earned_at"] is not None
        assert badges["level-25"]["earned_at"] is None

    async def test_marathon_grants_on_long_phase(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "e-ach-4",
                        "type": "focus_phase_completed",
                        "client_ts": "2026-01-01T00:00:00Z",
                        "payload": {"minutes": 50, "difficulty": "easy"},
                    }
                ]
            },
        )
        assert response.status_code == 200
        badges = await _badges(authenticated_async_client)
        assert badges["marathon"]["earned_at"] is not None
        assert badges["first-focus"]["earned_at"] is not None

    async def test_streak_and_perfect_day(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        daily = Daily(user_id=confirmed_user["id"], title="d", streak=8, active=True)
        db.add(daily)
        await db.flush()
        db.add(
            DailyCheck(
                daily_id=daily.id,
                daily_item_id=None,
                check_date=date(2025, 12, 31),
                done=True,
            )
        )
        await db.commit()
        await _score_event(authenticated_async_client, "e-ach-5")
        badges = await _badges(authenticated_async_client)
        assert badges["streak-7"]["earned_at"] is not None
        assert badges["streak-21"]["earned_at"] is None
        assert badges["perfect-day"]["earned_at"] is not None

    async def test_gear_buy_grants_first_gear(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], gold=100.0)
        await _buy(authenticated_async_client, "all-shield-1")
        badges = await _badges(authenticated_async_client)
        assert badges["first-gear"]["earned_at"] is not None

    async def test_class_pick_grants_badge(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], level=10)
        response = await authenticated_async_client.post(
            f"{CHAR}/class", json={"game_class": "rogue"}
        )
        assert response.status_code == 200
        # level-10 + class-picked grant at the pick (25 + 15 gold).
        assert response.json()["gold"] == pytest.approx(40.0)
        badges = await _badges(authenticated_async_client)
        assert badges["class-picked"]["earned_at"] is not None


# --- Death cascade (issue #64) -------------------------------------------------


async def _kill(client: AsyncClient, eid: str) -> None:
    """A 500-damage event — fatal from any HP total."""
    response = await client.post(
        f"{GAME}/events",
        json={
            "events": [
                {
                    "client_event_id": eid,
                    "type": "damage",
                    "client_ts": "2026-01-01T00:00:00Z",
                    "payload": {"amount": 500},
                }
            ]
        },
    )
    assert response.status_code == 200, response.text


async def _outcome(db: AsyncSession, user_id: int, eid: str) -> dict:
    result = await db.execute(
        select(GameEvent).where(
            GameEvent.user_id == user_id, GameEvent.client_event_id == eid
        )
    )
    return result.scalar_one().payload["_outcome"]


class TestDeathCascade:
    async def test_death_loses_the_only_losable_item(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(
            db, confirmed_user["id"], level=8, xp=10, gold=200.0, hp=1.0, str_stat=2
        )
        await _buy(authenticated_async_client, "all-shield-1")
        await _kill(authenticated_async_client, "e-death-1")

        outcome = await _outcome(db, confirmed_user["id"], "e-death-1")
        # Deterministic pick: the one losable item is the only candidate.
        assert outcome["died"] is True
        assert outcome["gear_lost"] is True
        assert outcome["gear_lost_key"] == "all-shield-1"
        assert outcome["stat_lost"] == "str_stat"

        row = await _profile_row(db, confirmed_user["id"])
        assert row.level == 7 and row.xp == 0 and row.gold == 0.0
        assert row.str_stat == 1
        items = await _gear(authenticated_async_client)
        assert items["all-shield-1"]["owned"] is False

    async def test_death_loses_exactly_one_of_two(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], gold=200.0, hp=1.0)
        await _buy(authenticated_async_client, "all-shield-1")
        await _buy(authenticated_async_client, "all-body-1")
        await _kill(authenticated_async_client, "e-death-2")

        outcome = await _outcome(db, confirmed_user["id"], "e-death-2")
        # Bounded randomness: the pick is always a real owned item, and
        # exactly one row leaves the inventory.
        assert outcome["gear_lost"] is True
        assert outcome["gear_lost_key"] in {"all-shield-1", "all-body-1"}
        items = await _gear(authenticated_async_client)
        owned = {k for k, r in items.items() if r["owned"]}
        assert len(owned) == 1
        assert outcome["gear_lost_key"] not in owned

    async def test_death_without_gear_reports_false(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], hp=1.0)
        await _kill(authenticated_async_client, "e-death-3")
        outcome = await _outcome(db, confirmed_user["id"], "e-death-3")
        assert outcome["died"] is True
        assert outcome["gear_lost"] is False
        assert outcome["gear_lost_key"] is None
