"""API tests for the character sheet: stat allocation, class, respec (#64)."""

import random
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.game import achievements, character_service, engine, service
from app.models.game import (
    Achievement,
    Daily,
    DailyCheck,
    GameEvent,
    GameProfile,
    GearItem,
    UserAchievement,
)

GAME = "/api/v1/game"
CHAR = "/api/v1/game/character"


@pytest.fixture(autouse=True)
def _no_crits(monkeypatch: pytest.MonkeyPatch) -> None:
    """The events endpoint scores with the module's unseeded `_rng`; a crit
    multiplies awards ~1.5-3x and flakes exact XP/gold/HP assertions."""
    monkeypatch.setattr(engine, "crit_roll", lambda *args, **kwargs: 1.0)


async def _ensure_profile(client: AsyncClient) -> dict:
    """Create the profile row (first GET autocreates) and return its JSON."""
    response = await client.get(f"{GAME}/profile")
    assert response.status_code == 200, response.text
    return response.json()


async def _set_profile(db: AsyncSession, user_id: int, **fields) -> None:
    await db.execute(update(GameProfile).where(GameProfile.user_id == user_id).values(**fields))
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
        await _set_profile(db, confirmed_user["id"], unspent_stat_points=5, str_stat=100)
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
            await authenticated_async_client.post(f"{CHAR}/allocate", json={"points": {"str": 0}})
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

        response = await authenticated_async_client.patch(f"{CHAR}", json={"auto_allocate": True})
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
        response = await authenticated_async_client.patch(f"{CHAR}", json={"auto_allocate": True})
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
            profile["str_stat"] + profile["int_stat"] + profile["con_stat"] + profile["per_stat"]
        )
        assert allocated == 1

    async def test_batch_level_up_distributes_before_next_event(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Mid-batch auto-distribute: a level-up point earned by event A is
        allocated before event B in the SAME batch scores — sequential
        single-request ordering. str_stat=1 pre-allocated so the point lands
        on INT (+2.5% XP — a deterministic, crit-free signal)."""
        monkeypatch.setattr(service, "_rng", random.Random(0))
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], auto_allocate=True, str_stat=1)
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "e-mid-a",
                        "type": "focus_phase_completed",
                        "client_ts": "2026-01-01T00:00:00Z",
                        "payload": {"minutes": 25, "difficulty": "easy"},
                    },
                    {
                        "client_event_id": "e-mid-b",
                        "type": "focus_phase_completed",
                        "client_ts": "2026-01-01T00:01:00Z",
                        "payload": {"minutes": 20, "difficulty": "easy"},
                    },
                ]
            },
        )
        assert response.status_code == 200, response.text
        # Event A: xp 25 -> level 2 + one point, auto-allocated to INT before
        # event B scores. B pays round(20 * 1.025) = 21 with the point in —
        # scored without it, B would pay 20.
        outcome = await _outcome(db, confirmed_user["id"], "e-mid-b")
        assert outcome["xp"] == 21
        profile = response.json()["profile"]
        assert profile["level"] == 2
        assert profile["xp"] == 21
        assert profile["int_stat"] == 1
        assert profile["unspent_stat_points"] == 0


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

    async def test_unknown_class_rejected(self, authenticated_async_client: AsyncClient) -> None:
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
        await _set_profile(db, confirmed_user["id"], level=10, game_class="mage", gold=50.0)
        response = await authenticated_async_client.post(f"{CHAR}/respec")
        assert response.status_code == 400

    async def test_respec_reopens_class_choice(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], level=10, game_class="mage", gold=200.0)
        assert (await authenticated_async_client.post(f"{CHAR}/respec")).status_code == 200
        response = await authenticated_async_client.post(
            f"{CHAR}/class", json={"game_class": "rogue"}
        )
        assert response.status_code == 200
        assert response.json()["game_class"] == "rogue"

    async def test_respec_repick_survives_death_level_drop(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """Class at 10 -> death to 9 -> respec -> re-pick still succeeds:
        class_unlocked makes the first pick's gate pass sticky."""
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], level=10, gold=200.0)
        response = await authenticated_async_client.post(
            f"{CHAR}/class", json={"game_class": "mage"}
        )
        assert response.status_code == 200, response.text
        await _kill(authenticated_async_client, "e-unlock-death")
        row = await _profile_row(db, confirmed_user["id"])
        assert row.level == 9 and row.game_class == "mage"
        assert row.class_unlocked is True
        # Death zeroed the gold the respec needs; top the balance back up.
        await _set_profile(db, confirmed_user["id"], gold=200.0)
        assert (await authenticated_async_client.post(f"{CHAR}/respec")).status_code == 200
        response = await authenticated_async_client.post(
            f"{CHAR}/class", json={"game_class": "rogue"}
        )
        assert response.status_code == 200, response.text
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
    return {row["key"]: row for row in response.json()["items"]}[key]


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
        assert warrior_slots == {"weapon", "shield", "head", "armor", "body", "back", "eyewear"}

    async def test_catalog_is_idempotent(self, authenticated_async_client: AsyncClient) -> None:
        first = await _gear(authenticated_async_client)
        second = await _gear(authenticated_async_client)
        assert [r["key"] for r in second.values()] == [r["key"] for r in first.values()]

    async def test_seed_upserts_drifted_rows(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A second ensure after a code-literal edit updates the DB row —
        the GEAR_CATALOG literal is authoritative over already-seeded data."""
        await _ensure_profile(authenticated_async_client)
        await _gear(authenticated_async_client)
        patched = [dict(row) for row in character_service.GEAR_CATALOG]
        drifted = next(row for row in patched if row["key"] == "all-shield-1")
        drifted["cost"] += 999
        monkeypatch.setattr(character_service, "GEAR_CATALOG", patched)

        items = await _gear(authenticated_async_client)
        assert items["all-shield-1"]["cost"] == drifted["cost"]
        # A real write commits the upsert — the stored row itself changed.
        await _set_profile(db, confirmed_user["id"], gold=500.0)
        await _buy(authenticated_async_client, "all-body-1")
        row = (
            await db.execute(select(GearItem).where(GearItem.key == "all-shield-1"))
        ).scalar_one()
        assert row.cost == drifted["cost"]

    async def test_seed_insert_tolerates_race(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Concurrency-shaped: the insert collides with rows a racing txn
        already committed — ON CONFLICT DO NOTHING, not an IntegrityError."""
        await _gear(authenticated_async_client)
        rows = [dict(r) for r in character_service.GEAR_CATALOG]
        await db.execute(character_service._insert_missing(db, rows))
        await db.commit()
        count = (await db.execute(select(func.count()).select_from(GearItem))).scalar_one()
        assert count == len(rows)


class TestGearBuy:
    async def test_buy_debits_gold_and_marks_owned(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], gold=150.0)
        response = await authenticated_async_client.post(
            f"{GEAR}/buy", json={"key": "all-shield-1"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        item = {r["key"]: r for r in body["items"]}["all-shield-1"]
        assert item["owned"] is True
        assert item["equipped"] is False
        # The debit lands on the response profile — no follow-up GET needed.
        # 150 - 50 cost + 10 first-gear badge.
        assert body["profile"]["gold"] == pytest.approx(110.0)
        row = await _profile_row(db, confirmed_user["id"])
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
        await _set_profile(db, confirmed_user["id"], level=10, game_class="mage", gold=500.0)
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
        await _set_profile(db, confirmed_user["id"], level=10, game_class="warrior", gold=500.0)
        response = await authenticated_async_client.post(
            f"{GEAR}/buy", json={"key": "warrior-weapon-2"}
        )
        assert response.status_code == 400
        await _buy(authenticated_async_client, "warrior-weapon-1")
        item = await _buy(authenticated_async_client, "warrior-weapon-2")
        assert item["owned"] is True

    async def test_buy_unknown_key_404(self, authenticated_async_client: AsyncClient) -> None:
        await _ensure_profile(authenticated_async_client)
        response = await authenticated_async_client.post(
            f"{GEAR}/buy", json={"key": "mystery-sword"}
        )
        assert response.status_code == 404


class TestGearEquip:
    async def _setup_warrior(self, client: AsyncClient, db: AsyncSession, user_id: int) -> None:
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
        body = response.json()
        # Profile rides the mutation response — the HUD reads stats/gold
        # without a follow-up GET.
        assert body["profile"]["level"] == 10
        items = {r["key"]: r for r in body["items"]}
        assert items["warrior-weapon-1"]["equipped"] is True
        response = await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "warrior-weapon-1", "equipped": False}
        )
        items = {r["key"]: r for r in response.json()["items"]}
        assert items["warrior-weapon-1"]["equipped"] is False

    async def test_profile_exposes_effective_stats(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """str_effective = allocated + equipped gear; str_stat stays allocated-only."""
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], game_class="warrior", gold=200.0, str_stat=4)
        await _buy(authenticated_async_client, "warrior-weapon-1")  # +3 str
        response = await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "warrior-weapon-1", "equipped": True}
        )
        assert response.status_code == 200, response.text
        # The mutation response carries the effective stats too.
        assert response.json()["profile"]["str_effective"] == 7
        profile = await _ensure_profile(authenticated_async_client)
        assert profile["str_stat"] == 4
        assert profile["str_effective"] == 7
        # Stats with no gear bonus report effective == allocated.
        assert profile["int_effective"] == profile["int_stat"]

    async def test_equip_bumps_same_slot(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        await _buy(authenticated_async_client, "warrior-weapon-2")
        await authenticated_async_client.post(f"{GEAR}/equip", json={"key": "warrior-weapon-1"})
        response = await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "warrior-weapon-2"}
        )
        items = {r["key"]: r for r in response.json()["items"]}
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
        await authenticated_async_client.post(f"{GEAR}/equip", json={"key": "warrior-weapon-1"})
        await authenticated_async_client.post(f"{GEAR}/equip", json={"key": "all-shield-1"})
        response = await authenticated_async_client.post(f"{CHAR}/respec")
        assert response.status_code == 200, response.text
        items = await _gear(authenticated_async_client)
        # Class piece stripped; the 'all' shield stays worn.
        assert items["warrior-weapon-1"]["equipped"] is False
        assert items["all-shield-1"]["equipped"] is True


class TestGearCostume:
    async def _setup_warrior(self, client: AsyncClient, db: AsyncSession, user_id: int) -> None:
        await _ensure_profile(client)
        await _set_profile(db, user_id, level=10, game_class="warrior", gold=600.0)
        await _buy(client, "warrior-weapon-1")
        await _buy(client, "all-shield-1")

    async def test_costume_on_and_off(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        response = await authenticated_async_client.post(
            f"{GEAR}/costume", json={"key": "warrior-weapon-1", "costume": True}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Profile rides the mutation response, same as equip.
        assert body["profile"]["level"] == 10
        items = {r["key"]: r for r in body["items"]}
        assert items["warrior-weapon-1"]["costume"] is True
        # Costume is independent: flagging doesn't equip.
        assert items["warrior-weapon-1"]["equipped"] is False
        response = await authenticated_async_client.post(
            f"{GEAR}/costume", json={"key": "warrior-weapon-1", "costume": False}
        )
        items = {r["key"]: r for r in response.json()["items"]}
        assert items["warrior-weapon-1"]["costume"] is False

    async def test_costume_bumps_same_slot(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        await _buy(authenticated_async_client, "warrior-weapon-2")
        await authenticated_async_client.post(f"{GEAR}/costume", json={"key": "warrior-weapon-1"})
        response = await authenticated_async_client.post(
            f"{GEAR}/costume", json={"key": "warrior-weapon-2"}
        )
        items = {r["key"]: r for r in response.json()["items"]}
        # One costume per slot: the tier-1 look yields to the tier-2.
        assert items["warrior-weapon-2"]["costume"] is True
        assert items["warrior-weapon-1"]["costume"] is False

    async def test_costume_rejects_unowned(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        response = await authenticated_async_client.post(
            f"{GEAR}/costume", json={"key": "warrior-armor-1"}
        )
        assert response.status_code == 400

    async def test_costume_rejects_unknown_key(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        response = await authenticated_async_client.post(
            f"{GEAR}/costume", json={"key": "mystery-sword"}
        )
        assert response.status_code == 400

    async def test_costume_and_equipped_coexist(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """The flags are independent: one item can be worn AND shown, and a
        same-slot costume pick never disturbs the equipped piece."""
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        await _buy(authenticated_async_client, "warrior-weapon-2")
        await authenticated_async_client.post(f"{GEAR}/equip", json={"key": "warrior-weapon-1"})
        await authenticated_async_client.post(f"{GEAR}/costume", json={"key": "warrior-weapon-1"})
        await authenticated_async_client.post(f"{GEAR}/costume", json={"key": "warrior-weapon-2"})
        await authenticated_async_client.post(f"{GEAR}/costume", json={"key": "all-shield-1"})
        items = await _gear(authenticated_async_client)
        # Costume moved to w2 in the same slot; the equip never did.
        assert items["warrior-weapon-1"]["equipped"] is True
        assert items["warrior-weapon-1"]["costume"] is False
        assert items["warrior-weapon-2"]["equipped"] is False
        assert items["warrior-weapon-2"]["costume"] is True
        assert items["all-shield-1"]["equipped"] is False
        assert items["all-shield-1"]["costume"] is True

    async def test_costume_survives_respec(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """Respec (class -> None) strips the worn warrior piece via
        unequip_mismatched but leaves the costume flag — the look is
        class-agnostic, so toggling it stays legal while re-equipping
        the cross-class piece is still rejected."""
        await self._setup_warrior(authenticated_async_client, db, confirmed_user["id"])
        await authenticated_async_client.post(f"{GEAR}/equip", json={"key": "warrior-weapon-1"})
        await authenticated_async_client.post(f"{GEAR}/costume", json={"key": "warrior-weapon-1"})
        assert (await authenticated_async_client.post(f"{CHAR}/respec")).status_code == 200
        items = await _gear(authenticated_async_client)
        assert items["warrior-weapon-1"]["equipped"] is False
        assert items["warrior-weapon-1"]["costume"] is True
        # Classless now: equip is class-locked, costume is not.
        response = await authenticated_async_client.post(
            f"{GEAR}/equip", json={"key": "warrior-weapon-1"}
        )
        assert response.status_code == 400
        response = await authenticated_async_client.post(
            f"{GEAR}/costume", json={"key": "warrior-weapon-1", "costume": False}
        )
        assert response.status_code == 200, response.text
        items = {r["key"]: r for r in response.json()["items"]}
        assert items["warrior-weapon-1"]["costume"] is False

    async def test_costume_gear_contributes_no_stat_bonus(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """Mirror of TestGearScoring.test_equipped_int_boosts_xp with the
        costume flag in place of equipped: gear_stat_bonus reads worn
        pieces only, so the look scores nothing."""
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], level=10, game_class="mage", gold=200.0)
        await _buy(authenticated_async_client, "mage-weapon-1")  # int +3
        response = await authenticated_async_client.post(
            f"{GEAR}/costume", json={"key": "mage-weapon-1"}
        )
        items = {r["key"]: r for r in response.json()["items"]}
        assert items["mage-weapon-1"]["costume"] is True
        assert items["mage-weapon-1"]["equipped"] is False
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "e-costume-xp",
                        "type": "focus_phase_completed",
                        "client_ts": "2026-01-01T00:00:00Z",
                        "payload": {"minutes": 10, "difficulty": "easy"},
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        # Equipped it would pay 11 (see TestGearScoring); costume-only pays base 10.
        assert response.json()["profile"]["xp"] == 10


class TestGearScoring:
    async def test_equipped_int_boosts_xp(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """Equipped stats feed scoring: mage weapon INT raises XP earned."""
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], level=10, game_class="mage", gold=200.0)
        await _buy(authenticated_async_client, "mage-weapon-1")  # int +3
        await authenticated_async_client.post(f"{GEAR}/equip", json={"key": "mage-weapon-1"})
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
        await authenticated_async_client.post(f"{GEAR}/equip", json={"key": "all-shield-1"})
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

    async def test_lost_gear_stops_scoring_mid_batch(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """Death mid-batch deletes the item AND its stat contribution: the
        follow-up damage scores without the lost shield's CON bonus."""
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], gold=100.0)
        await _buy(authenticated_async_client, "all-shield-1")  # con +1
        await authenticated_async_client.post(f"{GEAR}/equip", json={"key": "all-shield-1"})
        now = datetime.now(timezone.utc)
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "e-kill",
                        "type": "damage",
                        "client_ts": now.isoformat(),
                        "payload": {"amount": 500},
                    },
                    {
                        "client_event_id": "e-hit",
                        "type": "damage",
                        "client_ts": (now + timedelta(minutes=1)).isoformat(),
                        "payload": {"amount": 4},
                    },
                ]
            },
        )
        assert response.status_code == 200, response.text
        outcome = await _outcome(db, confirmed_user["id"], "e-kill")
        assert outcome["gear_lost_key"] == "all-shield-1"
        # Revive refills to 50; the hit loses the full 4 — a stale snapshot
        # would still shield for 1 - 1/250 and land only 3.
        assert response.json()["profile"]["hp"] == pytest.approx(46.0)


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


async def _daily_write_event(client: AsyncClient, eid: str) -> None:
    """One daily_check ledger row through ingest — the daily-gated criteria
    (perfect_day) only scan on writes that emit daily types, so eval
    triggers land here, not on focus events."""
    response = await client.post(
        f"{GAME}/events",
        json={
            "events": [
                {
                    "client_event_id": eid,
                    "type": "daily_check",
                    "client_ts": "2026-01-01T00:00:00Z",
                    # Unresolvable id -> applied-but-unscored row; the type
                    # still opens the daily-gated scans without touching marks.
                    "payload": {"daily_id": 999999, "done": True},
                }
            ]
        },
    )
    assert response.status_code == 200, response.text


class TestAchievements:
    async def test_registry_seeds_16_badges(self, authenticated_async_client: AsyncClient) -> None:
        badges = await _badges(authenticated_async_client)
        assert len(badges) == 16
        assert {
            "level-10",
            "level-25",
            "level-50",
            "first-focus",
            "first-habit",
            "first-daily",
            "first-gear",
            "class-picked",
            "focus-100",
            "focus-1000",
            "marathon",
            "streak-7",
            "streak-21",
            "perfect-day",
            "clicker-50",
            "first-record",
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
        await _daily_write_event(authenticated_async_client, "e-ach-5")
        badges = await _badges(authenticated_async_client)
        assert badges["streak-7"]["earned_at"] is not None
        assert badges["streak-21"]["earned_at"] is None
        assert badges["perfect-day"]["earned_at"] is not None

    async def test_perfect_day_counts_only_due_dailies(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """A daily not due that date can't block (or satisfy) the badge:
        the day's requirement is the recurrence-DUE subset, not all active."""
        await _ensure_profile(authenticated_async_client)
        check_day = datetime.now(timezone.utc).date() - timedelta(days=1)
        off_day = check_day - timedelta(days=1)
        every_day = Daily(
            user_id=confirmed_user["id"],
            title="d",
            recurrence={"kind": "daily"},
            active=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        # A weekday daily due on neither check day.
        off_schedule = Daily(
            user_id=confirmed_user["id"],
            title="m",
            recurrence={"kind": "weekdays", "days": [(check_day.weekday() + 3) % 7]},
            active=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        db.add_all([every_day, off_schedule])
        await db.flush()
        # Only the off-schedule daily checked on off_day — covers no due
        # daily (every_day was due and unchecked), so no badge yet.
        db.add(
            DailyCheck(
                daily_id=off_schedule.id,
                daily_item_id=None,
                check_date=off_day,
                done=True,
            )
        )
        await db.commit()
        await _daily_write_event(authenticated_async_client, "e-ach-pd1")
        badges = await _badges(authenticated_async_client)
        assert badges["perfect-day"]["earned_at"] is None
        # check_day: every due daily done (the unchecked weekday one isn't
        # due that date) -> perfect.
        db.add(
            DailyCheck(
                daily_id=every_day.id,
                daily_item_id=None,
                check_date=check_day,
                done=True,
            )
        )
        await db.commit()
        await _daily_write_event(authenticated_async_client, "e-ach-pd2")
        badges = await _badges(authenticated_async_client)
        assert badges["perfect-day"]["earned_at"] is not None

    async def test_perfect_day_counts_backfilled_old_days(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """A check written now for a >370d-old day still qualifies — the
        scan bound is on write recency (created_at), not the check date."""
        await _ensure_profile(authenticated_async_client)
        old_day = date.today() - timedelta(days=400)
        daily = Daily(
            user_id=confirmed_user["id"],
            title="d",
            streak=5,
            active=True,
            # The daily must already have existed on the backfilled day.
            created_at=datetime.combine(old_day - timedelta(days=30), datetime.min.time()),
        )
        db.add(daily)
        await db.flush()
        db.add(
            DailyCheck(
                daily_id=daily.id,
                daily_item_id=None,
                check_date=old_day,
                done=True,
            )
        )
        await db.commit()
        await _daily_write_event(authenticated_async_client, "e-ach-pd3")
        badges = await _badges(authenticated_async_client)
        assert badges["perfect-day"]["earned_at"] is not None

    async def test_perfect_day_grants_on_daily_delete(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """Deleting the unchecked daily makes the checked day perfect —
        the grant must land on the delete itself, not the next daily write."""
        await _ensure_profile(authenticated_async_client)
        checked = Daily(user_id=confirmed_user["id"], title="a", active=True)
        unchecked = Daily(user_id=confirmed_user["id"], title="b", active=True)
        db.add_all([checked, unchecked])
        await db.flush()
        db.add(
            DailyCheck(
                daily_id=checked.id,
                daily_item_id=None,
                check_date=date.today(),
                done=True,
            )
        )
        await db.commit()
        response = await authenticated_async_client.delete(f"{GAME}/dailies/{unchecked.id}")
        assert response.status_code == 200, response.text
        badges = await _badges(authenticated_async_client)
        assert badges["perfect-day"]["earned_at"] is not None

    async def test_perfect_day_reopen_sees_pre_window_checks(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """A check WRITTEN >370d ago is invisible to the bounded scan, but
        the due-shrinking reopen (delete) must re-scan full history — the
        day it checked can newly qualify once the blocking daily is gone."""
        await _ensure_profile(authenticated_async_client)
        checked = Daily(user_id=confirmed_user["id"], title="a", active=True)
        unchecked = Daily(user_id=confirmed_user["id"], title="b", active=True)
        db.add_all([checked, unchecked])
        await db.flush()
        db.add(
            DailyCheck(
                daily_id=checked.id,
                daily_item_id=None,
                check_date=date.today(),
                done=True,
                # Written before the 370d recency bound — only the
                # unbounded reopen can see it.
                created_at=datetime.now(timezone.utc) - timedelta(days=400),
            )
        )
        await db.commit()
        response = await authenticated_async_client.delete(f"{GAME}/dailies/{unchecked.id}")
        assert response.status_code == 200, response.text
        badges = await _badges(authenticated_async_client)
        assert badges["perfect-day"]["earned_at"] is not None

    async def test_event_gated_scans_skip_unrelated_writes(
        self,
        authenticated_async_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A write emitting no daily types skips perfect_day's check scan
        outright — the criterion can't newly pass, so the query never runs
        inside the profile lock."""
        await _ensure_profile(authenticated_async_client)
        calls = 0
        real_perfect_day = achievements._perfect_day

        async def spy(db: AsyncSession, user_id: int, full_history: bool = False) -> bool:
            nonlocal calls
            calls += 1
            return await real_perfect_day(db, user_id, full_history)

        monkeypatch.setattr(achievements, "_perfect_day", spy)
        # Applied habit_click write — emits no daily types, scan stays shut.
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "e-gate-1",
                        "type": "habit_click",
                        "client_ts": "2026-01-01T00:00:00Z",
                        # Unresolvable habit -> applied-but-unscored; eval
                        # still runs for the batch.
                        "payload": {"habit_id": 999999, "direction": "positive"},
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert calls == 0
        # A daily write opens the gate — the scan runs once.
        await _daily_write_event(authenticated_async_client, "e-gate-2")
        assert calls == 1

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

    async def test_malformed_first_criteria_never_grants(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """criteria={'kind': 'first'} with no 'what' must skip, not KeyError."""
        await _ensure_profile(authenticated_async_client)
        db.add(
            Achievement(
                key="bad-first",
                name="broken",
                description="first-criteria without a what",
                criteria={"kind": "first"},
                gold_reward=5,
            )
        )
        await db.commit()
        profile = await _score_event(authenticated_async_client, "e-bad-crit")
        # No 500 — and the malformed badge never grants.
        assert profile["gold"] == pytest.approx(12.0)  # 2 phase + 10 first-focus
        badges = await _badges(authenticated_async_client)
        assert badges["bad-first"]["earned_at"] is None

    async def test_missing_threshold_never_grants(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """criteria={'kind': 'level'} with no 'threshold' must not grant to all."""
        await _ensure_profile(authenticated_async_client)
        db.add(
            Achievement(
                key="bad-level",
                name="broken",
                description="level criteria without a threshold",
                criteria={"kind": "level"},
                gold_reward=5,
            )
        )
        await db.commit()
        profile = await _score_event(authenticated_async_client, "e-bad-thr")
        assert profile["gold"] == pytest.approx(12.0)
        badges = await _badges(authenticated_async_client)
        assert badges["bad-level"]["earned_at"] is None

    async def test_bool_threshold_never_grants(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """criteria={'kind': 'level', 'threshold': True} — int(True) is 1,
        which must not lower the bar into a grant-everything badge."""
        await _ensure_profile(authenticated_async_client)
        db.add(
            Achievement(
                key="bool-level",
                name="broken",
                description="level criteria with a bool threshold",
                criteria={"kind": "level", "threshold": True},
                gold_reward=5,
            )
        )
        await db.commit()
        profile = await _score_event(authenticated_async_client, "e-bool-thr")
        assert profile["gold"] == pytest.approx(12.0)
        badges = await _badges(authenticated_async_client)
        assert badges["bool-level"]["earned_at"] is None

    async def test_fractional_threshold_never_grants(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        """criteria={'kind': 'level', 'threshold': 10.5} — int() truncates
        to 10, which must not lower the bar into a reachable badge. Level 10
        makes this discriminating: the truncated threshold would grant."""
        await _ensure_profile(authenticated_async_client)
        await _set_profile(db, confirmed_user["id"], level=10)
        db.add(
            Achievement(
                key="frac-level",
                name="broken",
                description="level criteria with a fractional threshold",
                criteria={"kind": "level", "threshold": 10.5},
                gold_reward=5,
            )
        )
        await db.commit()
        profile = await _score_event(authenticated_async_client, "e-frac-thr")
        # 12.0 baseline + 25 for the legit level-10 badge; no frac-level grant.
        assert profile["gold"] == pytest.approx(37.0)
        badges = await _badges(authenticated_async_client)
        assert badges["frac-level"]["earned_at"] is None

    async def test_registry_upserts_drifted_rows(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A second ensure after a code-literal edit updates the DB row —
        the ACHIEVEMENTS literal is authoritative over already-seeded data."""
        await _badges(authenticated_async_client)
        patched = [dict(row) for row in achievements.ACHIEVEMENTS]
        drifted = next(row for row in patched if row["key"] == "focus-100")
        drifted["gold_reward"] += 555
        monkeypatch.setattr(achievements, "ACHIEVEMENTS", patched)

        badges = await _badges(authenticated_async_client)
        assert badges["focus-100"]["gold_reward"] == drifted["gold_reward"]
        # A real write commits the upsert — the stored row itself changed.
        await _score_event(authenticated_async_client, "e-upsert-ach")
        row = (
            await db.execute(select(Achievement).where(Achievement.key == "focus-100"))
        ).scalar_one()
        assert row.gold_reward == drifted["gold_reward"]

    async def test_registry_insert_tolerates_race(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Concurrency-shaped: the insert collides with rows a racing txn
        already committed — ON CONFLICT DO NOTHING, not an IntegrityError."""
        await _badges(authenticated_async_client)
        rows = [dict(r) for r in achievements.ACHIEVEMENTS]
        await db.execute(achievements._insert_missing(db, rows))
        await db.commit()
        count = (await db.execute(select(func.count()).select_from(Achievement))).scalar_one()
        assert count == len(rows)


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
        select(GameEvent).where(GameEvent.user_id == user_id, GameEvent.client_event_id == eid)
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
        await _set_profile(db, confirmed_user["id"], level=8, xp=10, gold=200.0, hp=1.0, str_stat=2)
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
