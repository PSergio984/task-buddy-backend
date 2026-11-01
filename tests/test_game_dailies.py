"""Tests for /api/v1/game/dailies + the miss sweep — issue #63.

Scoring math assumes GameRates defaults and a seeded RNG that never crits:
daily_check share=1 pays like a neutral habit click — xp = round(6 * share),
gold = ceil(share * (1 + 0.01 * streak)); daily_missed costs
floor(2 * difficulty * CON-shield) HP.
"""

import random
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.game import daily_service, daily_sweep, service
from app.models.game import Daily, DailyCheck, DailyItem, DailyMiss, GameEvent, GameProfile
from app.models.user import User

GAME = "/api/v1/game"
DAILIES = f"{GAME}/dailies"


@pytest.fixture(autouse=True)
def _seeded_rng(monkeypatch) -> None:
    """Deterministic rolls: seed 0's early draws stay above crit chance."""
    monkeypatch.setattr(service, "_rng", random.Random(0))
    monkeypatch.setattr(daily_service, "_rng", random.Random(0))
    monkeypatch.setattr(daily_sweep, "_rng", random.Random(0))


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _at(days_ago: int, hour: int = 12) -> datetime:
    day = _today() - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


async def _create(client: AsyncClient, **overrides) -> dict:
    body = {"title": "Meditate", **overrides}
    response = await client.post(DAILIES, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _check(client: AsyncClient, daily_id: int, **payload) -> dict:
    response = await client.post(f"{DAILIES}/{daily_id}/check", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


async def _get_daily_row(db: AsyncSession, daily_id: int) -> Daily:
    # populate_existing: the fixture's session may already hold this row from
    # seeding (expire_on_commit=False) — a plain select would return stale
    # streak values after the sweep's separate session commits.
    result = await db.execute(
        select(Daily).where(Daily.id == daily_id).execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def _make_daily(
    db: AsyncSession,
    *,
    recurrence: dict | None = None,
    created_days_ago: int = 2,
    streak: int = 0,
    hp: float = 50.0,
    items: int = 0,
    active: bool = True,
    email: str = "daily-owner@t.dev",
) -> tuple[User, Daily]:
    """Seed a user + profile + daily directly (sweep tests bypass the API)."""
    user = User(username=email.split("@")[0], email=email, password="x", confirmed=True)
    db.add(user)
    await db.flush()
    db.add(GameProfile(user_id=user.id, hp=hp))
    daily = Daily(
        user_id=user.id,
        title="d",
        recurrence=recurrence or {"kind": "daily"},
        streak=streak,
        active=active,
        created_at=_at(created_days_ago),
    )
    db.add(daily)
    await db.flush()
    for i in range(items):
        db.add(DailyItem(daily_id=daily.id, title=f"i{i}", position=i))
    await db.commit()
    return user, daily


async def _profile(db: AsyncSession, user_id: int) -> GameProfile:
    result = await db.execute(
        select(GameProfile)
        .where(GameProfile.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


# --- Recurrence evaluation --------------------------------------------------


class TestRecurrence:
    def test_daily_every_day(self) -> None:
        rec = daily_service.parse_recurrence({"kind": "daily"})
        anchor = date(2026, 5, 1)
        assert daily_service.is_schedulable(rec, date(2026, 5, 10), anchor)
        assert not daily_service.is_schedulable(rec, date(2026, 4, 30), anchor)

    def test_weekdays(self) -> None:
        rec = daily_service.parse_recurrence({"kind": "weekdays", "days": [0, 2]})
        anchor = date(2026, 5, 1)
        assert daily_service.is_schedulable(rec, date(2026, 5, 4), anchor)  # Monday
        assert not daily_service.is_schedulable(rec, date(2026, 5, 5), anchor)  # Tue

    def test_every_n_days(self) -> None:
        anchor = date(2026, 5, 1)
        rec = daily_service.parse_recurrence(
            {"kind": "every_n_days", "interval": 3, "anchor": "2026-05-01"}
        )
        assert daily_service.is_schedulable(rec, date(2026, 5, 1), anchor)
        assert not daily_service.is_schedulable(rec, date(2026, 5, 2), anchor)
        assert daily_service.is_schedulable(rec, date(2026, 5, 4), anchor)
        assert daily_service.is_schedulable(rec, date(2026, 5, 7), anchor)
        # Without an explicit anchor the creation day anchors the phase.
        rec_no_anchor = daily_service.parse_recurrence({"kind": "every_n_days", "interval": 3})
        assert daily_service.is_schedulable(rec_no_anchor, date(2026, 5, 4), anchor)
        assert not daily_service.is_schedulable(rec_no_anchor, date(2026, 5, 5), anchor)

    def test_times_per_week(self) -> None:
        rec = daily_service.parse_recurrence({"kind": "times_per_week", "count": 3})
        anchor = date(2026, 5, 4)  # a Monday
        # Every day at/after the anchor accepts a check-in.
        assert daily_service.is_schedulable(rec, date(2026, 5, 4), anchor)
        assert daily_service.is_schedulable(rec, date(2026, 5, 9), anchor)
        assert not daily_service.is_schedulable(rec, date(2026, 5, 3), anchor)
        # Scheduled units are ISO week-ends (Sundays).
        units = daily_service.scheduled_units(rec, anchor, anchor, date(2026, 5, 24))
        assert units == [date(2026, 5, 10), date(2026, 5, 17), date(2026, 5, 24)]

    def test_malformed_blobs_parse_none(self) -> None:
        for blob in (
            None,
            {},
            "daily",
            {"kind": "nope"},
            {"kind": "weekdays"},
            {"kind": "weekdays", "days": []},
            {"kind": "weekdays", "days": [7]},
            {"kind": "every_n_days", "interval": 0},
            {"kind": "times_per_week", "count": 9},
            [],
        ):
            assert daily_service.parse_recurrence(blob) is None, blob

    def test_prior_units_rolling_window(self) -> None:
        rec = daily_service.parse_recurrence({"kind": "weekdays", "days": [0, 2]})
        anchor = date(2026, 5, 1)
        prior = daily_service.prior_units(rec, anchor, date(2026, 5, 13), 6)
        # Scheduled days before Wed 5/13: Mon 5/11, Wed 5/6, Mon 5/4 — the
        # window stops at the anchor (Fri 5/1 isn't a scheduled weekday).
        assert prior == [date(2026, 5, 11), date(2026, 5, 6), date(2026, 5, 4)]

    def test_eval_due_grace_boundary(self) -> None:
        unit = date(2026, 5, 10)
        not_yet = datetime(2026, 5, 11, 2, 59, tzinfo=timezone.utc)
        due = datetime(2026, 5, 11, 3, 0, tzinfo=timezone.utc)
        assert not daily_service.eval_due(unit, not_yet)
        assert daily_service.eval_due(unit, due)


# --- CRUD -------------------------------------------------------------------


class TestDailyCrud:
    async def test_create_defaults(self, authenticated_async_client: AsyncClient) -> None:
        daily = await _create(authenticated_async_client)
        assert daily["title"] == "Meditate"
        assert daily["recurrence"] == {"kind": "daily"}
        assert daily["streak"] == 0
        assert daily["active"] is True
        assert daily["items"] == []
        assert daily["reminder_times"] == []
        assert daily["completed_today"] is False

    async def test_create_full_fields(self, authenticated_async_client: AsyncClient) -> None:
        daily = await _create(
            authenticated_async_client,
            title="Morning routine",
            notes="pre-work",
            difficulty="hard",
            recurrence={"kind": "weekdays", "days": [4, 0, 0]},
            reminder_times=["07:30"],
            items=[{"title": "b", "position": 5}, {"title": "a", "position": 0}],
        )
        assert daily["difficulty"] == "hard"
        assert daily["recurrence"] == {"kind": "weekdays", "days": [0, 4]}
        assert daily["reminder_times"] == ["07:30"]
        assert [(i["title"], i["position"], i["done_today"]) for i in daily["items"]] == [
            ("a", 0, False),
            ("b", 5, False),
        ]

    async def test_create_every_n_days_fills_anchor(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        daily = await _create(
            authenticated_async_client, recurrence={"kind": "every_n_days", "interval": 2}
        )
        assert daily["recurrence"] == {
            "kind": "every_n_days",
            "interval": 2,
            "anchor": _today().isoformat(),
        }

    @pytest.mark.parametrize(
        "recurrence",
        [
            {"kind": "nope"},
            {"kind": "weekdays"},
            {"kind": "weekdays", "days": []},
            {"kind": "weekdays", "days": [7]},
            {"kind": "every_n_days", "interval": 0},
            {"kind": "every_n_days", "interval": 400},
            {"kind": "times_per_week", "count": 0},
            {"kind": "times_per_week", "count": 8},
        ],
    )
    async def test_create_bad_recurrence_rejected(
        self, authenticated_async_client: AsyncClient, recurrence: dict
    ) -> None:
        response = await authenticated_async_client.post(
            DAILIES, json={"title": "x", "recurrence": recurrence}
        )
        assert response.status_code == 422, recurrence

    async def test_create_blank_title_and_bad_reminder_rejected(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        assert (
            await authenticated_async_client.post(DAILIES, json={"title": "  "})
        ).status_code == 422
        response = await authenticated_async_client.post(
            DAILIES, json={"title": "x", "reminder_times": ["8:00"]}
        )
        assert response.status_code == 422

    async def test_list_and_get_own_only(
        self, authenticated_async_client: AsyncClient, async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client, title="Mine")
        listed = await authenticated_async_client.get(DAILIES)
        assert [d["title"] for d in listed.json()] == ["Mine"]
        got = await authenticated_async_client.get(f"{DAILIES}/{daily['id']}")
        assert got.status_code == 200

        await async_client.post(
            "/api/v1/users/register",
            json={"username": "other", "email": "other@example.com", "password": "otherpassword"},
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
        assert (await async_client.get(DAILIES, headers=headers)).json() == []
        assert (
            await async_client.get(f"{DAILIES}/{daily['id']}", headers=headers)
        ).status_code == 404

    async def test_patch_fields_and_items_replace(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client, items=[{"title": "old"}])
        response = await authenticated_async_client.patch(
            f"{DAILIES}/{daily['id']}",
            json={
                "title": "New",
                "active": False,
                "recurrence": {"kind": "times_per_week", "count": 3},
                "items": [{"title": "x"}, {"title": "y"}],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == "New"
        assert body["active"] is False
        assert body["recurrence"] == {"kind": "times_per_week", "count": 3}
        assert [i["title"] for i in body["items"]] == ["x", "y"]
        items = (
            (await db.execute(select(DailyItem).where(DailyItem.daily_id == daily["id"])))
            .scalars()
            .all()
        )
        assert len(items) == 2

    async def test_patch_cannot_touch_streak(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        response = await authenticated_async_client.patch(
            f"{DAILIES}/{daily['id']}", json={"streak": 99}
        )
        assert response.status_code == 400
        assert (await _get_daily_row(db, daily["id"])).streak == 0

    async def test_patch_empty_and_null_rejected(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        daily = await _create(authenticated_async_client)
        assert (
            await authenticated_async_client.patch(f"{DAILIES}/{daily['id']}", json={})
        ).status_code == 400
        assert (
            await authenticated_async_client.patch(
                f"{DAILIES}/{daily['id']}", json={"difficulty": None}
            )
        ).status_code == 422

    async def test_delete(self, authenticated_async_client: AsyncClient) -> None:
        daily = await _create(authenticated_async_client)
        assert (
            await authenticated_async_client.delete(f"{DAILIES}/{daily['id']}")
        ).status_code == 200
        assert (await authenticated_async_client.get(f"{DAILIES}/{daily['id']}")).status_code == 404

    async def test_daily_cap(
        self, authenticated_async_client: AsyncClient, db: AsyncSession, confirmed_user: dict
    ) -> None:
        db.add_all(
            [
                Daily(user_id=confirmed_user["id"], title=f"d{i}", recurrence={"kind": "daily"})
                for i in range(daily_service.MAX_DAILIES_PER_USER - 1)
            ]
        )
        await db.commit()
        await _create(authenticated_async_client)  # reaches the cap — ok
        response = await authenticated_async_client.post(DAILIES, json={"title": "one too many"})
        assert response.status_code == 400

    async def test_requires_auth(self, async_client: AsyncClient) -> None:
        assert (await async_client.get(DAILIES)).status_code == 401
        assert (await async_client.post(DAILIES, json={"title": "x"})).status_code == 401


# --- Check scoring ----------------------------------------------------------


class TestDailyCheck:
    async def test_master_check_pays_and_streaks(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        body = await _check(authenticated_async_client, daily["id"])
        assert body["status"] == "applied"
        # Base: xp = round(6 * 1.0) = 6; streak now 1 -> gold = ceil(1.01) = 2.
        assert body["profile"]["xp_today"] == 6
        assert body["profile"]["gold_today"] == 2
        assert body["daily"]["streak"] == 1
        assert body["daily"]["completed_today"] is True
        row = await _get_daily_row(db, daily["id"])
        assert row.streak == 1
        event = (
            await db.execute(select(GameEvent).where(GameEvent.type == "daily_check"))
        ).scalar_one()
        assert event.payload["daily_id"] == daily["id"]
        assert event.payload["_outcome"]["scored"] is True
        assert event.payload["_outcome"]["share"] == 1.0

    async def test_partial_checklist_pays_proportionally(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(
            authenticated_async_client,
            items=[{"title": "a"}, {"title": "b"}, {"title": "c"}, {"title": "d"}],
        )
        item_id = daily["items"][0]["id"]
        body = await _check(authenticated_async_client, daily["id"], daily_item_id=item_id)
        # share = 1/4, streak 0: xp = round(6 * .25) = 2, gold = ceil(.25) = 1
        assert body["profile"]["xp_today"] == 2
        assert body["profile"]["gold_today"] == 1
        assert body["daily"]["streak"] == 0
        assert body["daily"]["completed_today"] is False
        assert body["daily"]["items"][0]["done_today"] is True

        # Checking the remaining three completes the checklist: each still
        # pays its quarter; the last one bumps the streak.
        for i in (1, 2, 3):
            body = await _check(
                authenticated_async_client, daily["id"], daily_item_id=daily["items"][i]["id"]
            )
        assert body["daily"]["completed_today"] is True
        assert body["daily"]["streak"] == 1
        # Total xp = 2 * 3 + round(6 * .25) with streak=1 still 2 -> 8.
        assert body["profile"]["xp_today"] == 8

    async def test_master_check_pays_remaining_share(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        daily = await _create(authenticated_async_client, items=[{"title": "a"}, {"title": "b"}])
        first = await _check(
            authenticated_async_client, daily["id"], daily_item_id=daily["items"][0]["id"]
        )
        # Item share = 1/2: xp = round(6 * .5) = 3, gold = ceil(.5) = 1.
        assert first["profile"]["xp_today"] == 3
        body = await _check(authenticated_async_client, daily["id"])
        # Master pays the unpaid half: another xp = round(6 * .5) = 3.
        assert body["profile"]["xp_today"] == 6
        assert body["daily"]["streak"] == 1

    async def test_streak_bonus_scales_gold(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        await db.execute(update(Daily).where(Daily.id == daily["id"]).values(streak=10))
        await db.commit()
        body = await _check(authenticated_async_client, daily["id"])
        # streak becomes 11: gold = ceil(1 * 1.11) = 2 (vs 1 without bonus).
        assert body["profile"]["gold_today"] == 2
        assert body["daily"]["streak"] == 11

    async def test_check_off_schedule_pays_without_streak(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # Scheduled only on weekday 6 (Sunday); today is never a schedulable
        # miss for this daily unless today IS Sunday — build the rule off the
        # real weekday so the test is date-independent.
        today = _today()
        off_day = (today.weekday() + 3) % 7
        daily = await _create(
            authenticated_async_client, recurrence={"kind": "weekdays", "days": [off_day]}
        )
        body = await _check(authenticated_async_client, daily["id"])
        assert body["profile"]["xp_today"] == 6
        assert body["daily"]["streak"] == 0
        assert body["daily"]["completed_today"] is True

    async def test_already_checked_records_unscored(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        first = await _check(authenticated_async_client, daily["id"], client_event_id="c-1")
        assert first["status"] == "applied"
        # Same eid replays as a duplicate; a NEW eid lands unscored, not paid.
        replay = await _check(authenticated_async_client, daily["id"], client_event_id="c-1")
        assert replay["status"] == "duplicate"
        again = await _check(authenticated_async_client, daily["id"], client_event_id="c-2")
        assert again["status"] == "applied"
        assert again["profile"]["xp_today"] == 6  # not 12
        events = (
            (
                await db.execute(
                    select(GameEvent).where(GameEvent.type == "daily_check").order_by(GameEvent.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 2
        assert events[1].payload["_outcome"] == {"scored": False, "reason": "already_checked"}

    async def test_item_check_on_done_day_is_unscored(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        daily = await _create(authenticated_async_client, items=[{"title": "a"}])
        await _check(authenticated_async_client, daily["id"])
        body = await _check(
            authenticated_async_client, daily["id"], daily_item_id=daily["items"][0]["id"]
        )
        assert body["profile"]["xp_today"] == 6

    async def test_check_item_validation(self, authenticated_async_client: AsyncClient) -> None:
        daily = await _create(authenticated_async_client, items=[{"title": "a"}])
        other = await _create(authenticated_async_client, title="other", items=[{"title": "z"}])
        foreign_item = other["items"][0]["id"]
        assert (
            await authenticated_async_client.post(
                f"{DAILIES}/{daily['id']}/check", json={"daily_item_id": foreign_item}
            )
        ).status_code == 400
        # Whole-daily check on a daily with no items is the normal path; an
        # item check on an itemless daily 400s too.
        plain = await _create(authenticated_async_client, title="plain")
        assert (
            await authenticated_async_client.post(
                f"{DAILIES}/{plain['id']}/check", json={"daily_item_id": foreign_item}
            )
        ).status_code == 400

    async def test_check_date_bounds(self, authenticated_async_client: AsyncClient) -> None:
        daily = await _create(authenticated_async_client)
        tomorrow = (_today() + timedelta(days=1)).isoformat()
        assert (
            await authenticated_async_client.post(
                f"{DAILIES}/{daily['id']}/check", json={"check_date": tomorrow}
            )
        ).status_code == 400
        before_creation = (date(2000, 1, 1)).isoformat()
        assert (
            await authenticated_async_client.post(
                f"{DAILIES}/{daily['id']}/check", json={"check_date": before_creation}
            )
        ).status_code == 400

    async def test_backfill_yesterday_via_check_date(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        # Backdate creation so yesterday is a valid check day.
        await db.execute(update(Daily).where(Daily.id == daily["id"]).values(created_at=_at(1)))
        await db.commit()
        yesterday = (_today() - timedelta(days=1)).isoformat()
        body = await _check(authenticated_async_client, daily["id"], check_date=yesterday)
        assert body["daily"]["streak"] == 1
        check = (
            await db.execute(select(DailyCheck).where(DailyCheck.daily_id == daily["id"]))
        ).scalar_one()
        assert check.check_date.isoformat() == yesterday

    async def test_inactive_daily_rejects_checks(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        daily = await _create(authenticated_async_client)
        await authenticated_async_client.patch(f"{DAILIES}/{daily['id']}", json={"active": False})
        assert (
            await authenticated_async_client.post(f"{DAILIES}/{daily['id']}/check", json={})
        ).status_code == 400

    async def test_uncheck_master_unmarks_day(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        first = await _check(authenticated_async_client, daily["id"])
        assert first["profile"]["xp_today"] == 6
        body = await _check(authenticated_async_client, daily["id"], done=False)
        assert body["daily"]["completed_today"] is False
        assert body["profile"]["xp_today"] == 6  # uncheck never claws back
        # The ledger records the uncheck as applied-but-unpaid.
        stored = (
            (
                await db.execute(
                    select(GameEvent)
                    .where(GameEvent.type == "daily_check")
                    .order_by(GameEvent.id.desc())
                )
            )
            .scalars()
            .first()
        )
        assert stored.payload["done"] is False
        assert stored.payload["_outcome"]["uncheck"] is True
        assert stored.payload["_outcome"]["xp"] == 0

    async def test_uncheck_item_unmarks_master(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client, items=[{"title": "a"}, {"title": "b"}])
        item_id = daily["items"][0]["id"]
        await _check(authenticated_async_client, daily["id"], daily_item_id=item_id)
        await _check(authenticated_async_client, daily["id"])  # master completes the day
        body = await _check(
            authenticated_async_client, daily["id"], daily_item_id=item_id, done=False
        )
        # Unmarking an open-check item un-completes the day.
        assert body["daily"]["completed_today"] is False
        assert body["daily"]["items"][0]["done_today"] is False
        # Item b was never item-checked — the master check marks the day,
        # not the individual rows.
        assert body["daily"]["items"][1]["done_today"] is False

    async def test_uncheck_nothing_records_unscored(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        body = await _check(authenticated_async_client, daily["id"], done=False)
        assert body["profile"]["xp_today"] == 0
        stored = (
            await db.execute(select(GameEvent).where(GameEvent.type == "daily_check"))
        ).scalar_one()
        assert stored.payload["_outcome"] == {"scored": False, "reason": "nothing_to_uncheck"}

    async def test_recheck_after_uncheck_pays_nothing(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        await _check(authenticated_async_client, daily["id"])
        await _check(authenticated_async_client, daily["id"], done=False)
        # Restoring the mark can't re-pay the share or re-bump the streak.
        body = await _check(authenticated_async_client, daily["id"])
        assert body["profile"]["xp_today"] == 6  # not 12
        assert body["daily"]["streak"] == 1  # not 2
        assert body["daily"]["completed_today"] is True

    async def test_item_recheck_after_uncheck_restores_free(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client, items=[{"title": "a"}, {"title": "b"}])
        item_id = daily["items"][0]["id"]
        first = await _check(authenticated_async_client, daily["id"], daily_item_id=item_id)
        assert first["profile"]["xp_today"] == 3
        await _check(authenticated_async_client, daily["id"], daily_item_id=item_id, done=False)
        body = await _check(authenticated_async_client, daily["id"], daily_item_id=item_id)
        # Restored mark pays nothing; item b is still open so the day is not
        # complete.
        assert body["profile"]["xp_today"] == 3
        assert body["daily"]["completed_today"] is False

    async def test_check_then_event_replay_dedupes(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        await _check(authenticated_async_client, daily["id"], client_event_id="c-1")
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "c-1",
                        "type": "daily_check",
                        "client_ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {"daily_id": daily["id"]},
                    }
                ]
            },
        )
        assert response.json()["duplicates"] == 1
        assert (await _get_daily_row(db, daily["id"])).streak == 1


class TestDailyCheckEventSync:
    """Offline-queued daily_check events resolve stored state like habit clicks."""

    def _event(self, eid: str, payload: dict, days_ago: int = 0) -> dict:
        return {
            "client_event_id": eid,
            "type": "daily_check",
            "client_ts": _at(days_ago).isoformat(),
            "payload": payload,
        }

    async def test_synced_check_scores_server_side(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    # Client-forged share/streak/auto fields must not reach
                    # the engine or the ledger's authoritative keys.
                    self._event(
                        "d-1",
                        {"daily_id": daily["id"], "share": 1.0, "streak": 999, "auto": True},
                    )
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["applied"] == 1
        assert response.json()["profile"]["xp_today"] == 6
        assert (await _get_daily_row(db, daily["id"])).streak == 1
        stored = (
            (await db.execute(select(GameEvent).where(GameEvent.client_event_id == "d-1")))
            .scalar_one()
            .payload
        )
        assert stored["streak"] == 1
        assert stored["_outcome"]["streak"] == 1
        assert "auto" not in stored  # server-reserved marker stripped

    async def test_synced_check_unresolvable_records_unscored(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    self._event("d-1", {"daily_id": 999999}),
                    self._event("d-2", {"daily_id": "nope"}),
                ]
            },
        )
        assert response.json()["applied"] == 2
        for eid, reason in (("d-1", "daily_unresolvable"), ("d-2", "daily_unresolvable")):
            stored = (
                (await db.execute(select(GameEvent).where(GameEvent.client_event_id == eid)))
                .scalar_one()
                .payload
            )
            assert stored["_outcome"] == {"scored": False, "reason": reason}

    async def test_synced_check_backfills_to_client_day(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        await db.execute(update(Daily).where(Daily.id == daily["id"]).values(created_at=_at(2)))
        await db.commit()
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={"events": [self._event("d-1", {"daily_id": daily["id"]}, days_ago=1)]},
        )
        assert response.json()["applied"] == 1
        check = (
            await db.execute(select(DailyCheck).where(DailyCheck.daily_id == daily["id"]))
        ).scalar_one()
        assert check.check_date == _today() - timedelta(days=1)

    async def test_synced_uncheck_flips_mark(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        daily = await _create(authenticated_async_client)
        await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    self._event("d-1", {"daily_id": daily["id"]}),
                    self._event("d-2", {"daily_id": daily["id"], "done": False}),
                ]
            },
        )
        marks = (
            (await db.execute(select(DailyCheck).where(DailyCheck.daily_id == daily["id"])))
            .scalars()
            .all()
        )
        assert len(marks) == 1
        assert marks[0].done is False
        stored = (
            (await db.execute(select(GameEvent).where(GameEvent.client_event_id == "d-2")))
            .scalar_one()
            .payload
        )
        assert stored["done"] is False
        assert stored["_outcome"]["uncheck"] is True

    async def test_client_cannot_claim_daily_missed(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        # daily_missed is a server-authored type — rejected at the schema.
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "x-1",
                        "type": "daily_missed",
                        "client_ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {},
                    }
                ]
            },
        )
        assert response.status_code == 422


# --- Miss sweep -------------------------------------------------------------


class TestDailySweep:
    async def _miss_rows(self, db: AsyncSession, daily_id: int) -> list[DailyMiss]:
        result = await db.execute(select(DailyMiss).where(DailyMiss.daily_id == daily_id))
        return list(result.scalars().all())

    async def _events(self, db: AsyncSession, user_id: int, type_: str) -> list[GameEvent]:
        result = await db.execute(
            select(GameEvent).where(GameEvent.user_id == user_id, GameEvent.type == type_)
        )
        return list(result.scalars().all())

    async def test_missed_day_costs_hp_and_records(self, db: AsyncSession) -> None:
        user, daily = await _make_daily(db, created_days_ago=1, streak=5)
        # One due unit (yesterday), no prior misses -> freeze absorbs.
        recorded = await daily_sweep.run_daily_miss_sweep(now=_at(0, 4))
        assert recorded == 1
        misses = await self._miss_rows(db, daily.id)
        assert len(misses) == 1
        assert misses[0].scheduled_day == _today() - timedelta(days=1)
        assert misses[0].frozen is True
        assert misses[0].hp_lost == 2
        # Freeze preserved the streak; HP still applied.
        assert (await _get_daily_row(db, daily.id)).streak == 5
        assert (await _profile(db, user.id)).hp == 48
        events = await self._events(db, user.id, "daily_missed")
        assert len(events) == 1
        assert events[0].payload["_outcome"]["frozen"] is True
        assert events[0].payload["_outcome"]["streak_after"] == 5

    async def test_second_miss_breaks_streak(self, db: AsyncSession) -> None:
        user, daily = await _make_daily(db, created_days_ago=2, streak=5)
        # Two due units: first frozen, second unfrozen -> streak resets.
        recorded = await daily_sweep.run_daily_miss_sweep(now=_at(0, 4))
        assert recorded == 2
        misses = sorted(await self._miss_rows(db, daily.id), key=lambda m: m.scheduled_day)
        assert [m.frozen for m in misses] == [True, False]
        assert (await _get_daily_row(db, daily.id)).streak == 0
        assert (await _profile(db, user.id)).hp == 46  # 2 hp per miss

    async def test_completed_day_is_not_missed(self, db: AsyncSession) -> None:
        user, daily = await _make_daily(db, created_days_ago=1, streak=3)
        yesterday = _today() - timedelta(days=1)
        db.add(DailyCheck(daily_id=daily.id, daily_item_id=None, check_date=yesterday))
        await db.commit()
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 0
        assert await self._miss_rows(db, daily.id) == []
        assert (await _profile(db, user.id)).hp == 50

    async def test_sweep_is_idempotent(self, db: AsyncSession) -> None:
        # Two overlapping ticks (ADR 0001 rolling deploy) record once.
        user, daily = await _make_daily(db, created_days_ago=1, streak=5)
        first = await daily_sweep.run_daily_miss_sweep(now=_at(0, 4))
        second = await daily_sweep.run_daily_miss_sweep(now=_at(0, 5))
        third = await daily_sweep.run_daily_miss_sweep(now=_at(0, 6))
        assert first == 1 and second == 0 and third == 0
        assert len(await self._miss_rows(db, daily.id)) == 1
        assert len(await self._events(db, user.id, "daily_missed")) == 1
        assert (await _profile(db, user.id)).hp == 48

    async def test_day_before_grace_is_not_due(self, db: AsyncSession) -> None:
        _, daily = await _make_daily(db, created_days_ago=1)
        # 02:00 next-day: inside the 3h grace window.
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 2)) == 0
        assert await self._miss_rows(db, daily.id) == []

    async def test_times_per_week_quota_miss(self, db: AsyncSession) -> None:
        # count=2; anchored last Monday; only one completed day in the week.
        anchor_monday = _today() - timedelta(days=_today().weekday() + 7)
        _, daily = await _make_daily(
            db,
            recurrence={"kind": "times_per_week", "count": 2},
            created_days_ago=(_today() - anchor_monday).days,
        )
        db.add(DailyCheck(daily_id=daily.id, daily_item_id=None, check_date=anchor_monday))
        await db.commit()
        # Evaluate after last Sunday's day-end + grace.
        sunday = anchor_monday + timedelta(days=6)
        now = datetime.combine(sunday + timedelta(days=1), datetime.min.time()).replace(
            hour=4, tzinfo=timezone.utc
        )
        assert await daily_sweep.run_daily_miss_sweep(now=now) == 1
        misses = await self._miss_rows(db, daily.id)
        assert misses[0].scheduled_day == sunday

    async def test_times_per_week_quota_met(self, db: AsyncSession) -> None:
        anchor_monday = _today() - timedelta(days=_today().weekday() + 7)
        _, daily = await _make_daily(
            db,
            recurrence={"kind": "times_per_week", "count": 2},
            created_days_ago=(_today() - anchor_monday).days,
        )
        db.add_all(
            [
                DailyCheck(
                    daily_id=daily.id,
                    daily_item_id=None,
                    check_date=anchor_monday + timedelta(days=i),
                )
                for i in (0, 3)
            ]
        )
        await db.commit()
        sunday = anchor_monday + timedelta(days=6)
        now = datetime.combine(sunday + timedelta(days=1), datetime.min.time()).replace(
            hour=4, tzinfo=timezone.utc
        )
        assert await daily_sweep.run_daily_miss_sweep(now=now) == 0

    async def test_inactive_daily_is_skipped(self, db: AsyncSession) -> None:
        _, daily = await _make_daily(db, created_days_ago=1, active=False)
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 0
        assert await self._miss_rows(db, daily.id) == []

    async def test_malformed_recurrence_is_skipped(self, db: AsyncSession) -> None:
        _, daily = await _make_daily(db, created_days_ago=1, recurrence={"kind": "nope"})
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 0
        assert await self._miss_rows(db, daily.id) == []

    async def test_weekday_recurrence_only_charges_scheduled_days(self, db: AsyncSession) -> None:
        # Scheduled yesterday's weekday only — the day before is not a unit.
        yesterday = _today() - timedelta(days=1)
        _, daily = await _make_daily(
            db,
            created_days_ago=3,
            recurrence={"kind": "weekdays", "days": [yesterday.weekday()]},
        )
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 1
        misses = await self._miss_rows(db, daily.id)
        assert [m.scheduled_day for m in misses] == [yesterday]
