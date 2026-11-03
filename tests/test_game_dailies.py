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

from app.crud import game as game_crud
from app.game import daily_service, daily_sweep, engine, service
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

    def test_times_per_week_skips_impossible_first_week(self) -> None:
        rec = daily_service.parse_recurrence({"kind": "times_per_week", "count": 4})
        anchor = date(2026, 5, 8)  # a Friday — its week offers only 3 check days
        units = daily_service.scheduled_units(rec, anchor, anchor, date(2026, 5, 31))
        # The unsatisfiable partial week (Sun 5/10) is skipped.
        assert units == [date(2026, 5, 17), date(2026, 5, 24), date(2026, 5, 31)]
        # …and is not a freeze-window prior either.
        assert daily_service.prior_units(rec, anchor, date(2026, 5, 24), 6) == [date(2026, 5, 17)]
        # A full-week floor keeps its first unit.
        assert daily_service.scheduled_units(
            rec, date(2026, 5, 4), date(2026, 5, 4), date(2026, 5, 10)
        ) == [date(2026, 5, 10)]

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
        assert body["recurrence"] == {
            "kind": "times_per_week",
            "count": 3,
            "since": _today().isoformat(),
        }
        assert [i["title"] for i in body["items"]] == ["x", "y"]
        items = (
            (await db.execute(select(DailyItem).where(DailyItem.daily_id == daily["id"])))
            .scalars()
            .all()
        )
        assert len(items) == 2

    async def test_patch_explicit_every_n_days_anchor(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # An explicit anchor is a real `date` on the schema — the PATCH dump
        # must serialize it into the JSONB recurrence or commit fails.
        daily = await _create(authenticated_async_client)
        response = await authenticated_async_client.patch(
            f"{DAILIES}/{daily['id']}",
            json={"recurrence": {"kind": "every_n_days", "interval": 5, "anchor": "2026-05-01"}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["recurrence"] == {
            "kind": "every_n_days",
            "interval": 5,
            "anchor": "2026-05-01",
            "since": _today().isoformat(),
        }
        assert (await _get_daily_row(db, daily["id"])).recurrence["anchor"] == "2026-05-01"

    async def test_patch_every_n_days_without_anchor_keeps_stored(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # A recurrence PATCH that omits the anchor must preserve the stored
        # phase — filling it with the PATCH day silently re-anchors the
        # schedule (right on create, wrong on update).
        daily = await _create(
            authenticated_async_client,
            recurrence={"kind": "every_n_days", "interval": 3, "anchor": "2020-01-01"},
        )
        response = await authenticated_async_client.patch(
            f"{DAILIES}/{daily['id']}",
            json={"recurrence": {"kind": "every_n_days", "interval": 5}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["recurrence"]["anchor"] == "2020-01-01"
        assert (await _get_daily_row(db, daily["id"])).recurrence["anchor"] == "2020-01-01"

    async def test_identical_recurrence_patch_preserves_since(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # A schedule-identical PATCH must carry the stored `since` forward,
        # not re-stamp it (re-stamping to today would orphan the days the
        # current schedule already owns) or drop it (re-exposing the days
        # the stamp excluded). Seeded back-dated so a re-stamp shows.
        daily = await _create(authenticated_async_client)
        since = (_today() - timedelta(days=10)).isoformat()
        await db.execute(
            update(Daily)
            .where(Daily.id == daily["id"])
            .values(recurrence={"kind": "weekdays", "days": [1, 3], "since": since})
        )
        await db.commit()
        response = await authenticated_async_client.patch(
            f"{DAILIES}/{daily['id']}", json={"recurrence": {"kind": "weekdays", "days": [3, 1]}}
        )
        assert response.status_code == 200, response.text
        assert response.json()["recurrence"]["since"] == since
        assert (await _get_daily_row(db, daily["id"])).recurrence["since"] == since

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

        # Checking the remaining three completes the checklist; the last one
        # bumps the streak. Residual accounting bounds the day at the
        # whole-check amount: items 2-3 pay their quarter (2 xp each) and
        # item 4's quarter is clamped to the 0-xp unpaid residual — the day
        # can never pay more than a single whole check (per-fragment
        # rounding can't inflate the total).
        for i in (1, 2, 3):
            body = await _check(
                authenticated_async_client, daily["id"], daily_item_id=daily["items"][i]["id"]
            )
        assert body["daily"]["completed_today"] is True
        assert body["daily"]["streak"] == 1
        assert body["profile"]["xp_today"] == 6
        # Gold settles at the whole-check amount for the final streak:
        # fragments 2-3 were clamped to the unpaid gold residual, item 4's
        # residual at streak 1 pays the remaining 1 (total ceil(1.01) = 2).
        assert body["profile"]["gold_today"] == 2

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

    async def test_items_replaced_midday_master_pays_residual(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        # Replacing the checklist cascade-deletes the item marks — the
        # scored ledger rows are the only remaining proof half the day
        # already paid. The master check must still be clamped to the
        # residual, not re-pay a full share.
        daily = await _create(authenticated_async_client, items=[{"title": "a"}, {"title": "b"}])
        first = await _check(
            authenticated_async_client, daily["id"], daily_item_id=daily["items"][0]["id"]
        )
        assert first["profile"]["xp_today"] == 3  # half share
        response = await authenticated_async_client.patch(
            f"{DAILIES}/{daily['id']}", json={"items": [{"title": "x"}, {"title": "y"}]}
        )
        assert response.status_code == 200, response.text
        body = await _check(authenticated_async_client, daily["id"])
        # Without the residual clamp the raw master share (2-0 done)/2 = 1.0
        # would re-pay the whole day; the day totals exactly the whole check.
        assert body["profile"]["xp_today"] == 6
        assert body["profile"]["gold_today"] == 2  # whole-check at streak 1
        assert body["daily"]["streak"] == 1
        assert body["daily"]["completed_today"] is True

    async def test_backfill_after_missed_day_pays_without_streak(
        self, authenticated_async_client: AsyncClient, db: AsyncSession, confirmed_user: dict
    ) -> None:
        # The sweep already charged yesterday as missed; the streak freeze
        # preserved the streak — a backfill pays the share but can't
        # retro-credit the streak a second time.
        daily = await _create(authenticated_async_client)
        yesterday = _today() - timedelta(days=1)
        await db.execute(
            update(Daily).where(Daily.id == daily["id"]).values(created_at=_at(1), streak=5)
        )
        db.add(
            DailyMiss(
                daily_id=daily["id"],
                user_id=confirmed_user["id"],
                scheduled_day=yesterday,
                frozen=True,
            )
        )
        await db.commit()
        body = await _check(
            authenticated_async_client, daily["id"], check_date=yesterday.isoformat()
        )
        assert body["profile"]["xp_today"] == 6  # share still pays
        assert body["daily"]["streak"] == 5  # no retro streak credit
        check = (
            await db.execute(select(DailyCheck).where(DailyCheck.daily_id == daily["id"]))
        ).scalar_one()
        assert check.check_date == yesterday

    async def test_backfill_after_missed_week_pays_without_streak(
        self, authenticated_async_client: AsyncClient, db: AsyncSession, confirmed_user: dict
    ) -> None:
        # A times_per_week miss is charged at the unit — the week's Sunday —
        # not the missed day. A backfill landing mid-week inside a charged
        # week still pays the share but can't retro-credit the streak, and
        # neither can one landing exactly on the Sunday unit key.
        daily = await _create(
            authenticated_async_client, recurrence={"kind": "times_per_week", "count": 3}
        )
        sunday = daily_service.week_end(_today() - timedelta(days=7))
        midweek = sunday - timedelta(days=3)
        await db.execute(
            update(Daily).where(Daily.id == daily["id"]).values(created_at=_at(14), streak=5)
        )
        db.add(
            DailyMiss(
                daily_id=daily["id"],
                user_id=confirmed_user["id"],
                scheduled_day=sunday,
                frozen=True,
            )
        )
        await db.commit()
        body = await _check(authenticated_async_client, daily["id"], check_date=midweek.isoformat())
        assert body["profile"]["xp_today"] == 6  # share still pays
        assert body["daily"]["streak"] == 5  # no retro streak credit
        check = (
            await db.execute(select(DailyCheck).where(DailyCheck.daily_id == daily["id"]))
        ).scalar_one()
        assert check.check_date == midweek

        body = await _check(authenticated_async_client, daily["id"], check_date=sunday.isoformat())
        assert body["profile"]["xp_today"] == 12  # the second day pays too
        assert body["daily"]["streak"] == 5

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

    async def test_streak_over_bound_still_scores(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # A legit streak past the economy bound stays scorable — the gold
        # bonus saturates at +10000% instead of wedging the daily forever.
        daily = await _create(authenticated_async_client)
        await db.execute(update(Daily).where(Daily.id == daily["id"]).values(streak=10000))
        await db.commit()
        body = await _check(authenticated_async_client, daily["id"])
        assert body["profile"]["xp_today"] == 6
        assert body["profile"]["gold_today"] == 101  # ceil(1 * (1 + 0.01 * 10000))
        assert body["daily"]["streak"] == 10001

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

    async def test_rejected_synced_check_leaves_no_mark_or_streak(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # score_check validates lazily: a bogus stored difficulty raises in
        # apply_event AFTER the mark + streak bump staged — recording the
        # event unscored must roll that state back too, or a rejected check
        # would still write marks and streak at commit.
        daily = await _create(authenticated_async_client)
        await db.execute(
            update(Daily).where(Daily.id == daily["id"]).values(difficulty="bogus", streak=5)
        )
        await db.commit()
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={"events": [self._event("d-1", {"daily_id": daily["id"]})]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["applied"] == 1
        assert response.json()["profile"]["xp_today"] == 0
        # No mark, no streak change — only the unscored ledger row lands.
        marks = (
            (await db.execute(select(DailyCheck).where(DailyCheck.daily_id == daily["id"])))
            .scalars()
            .all()
        )
        assert marks == []
        assert (await _get_daily_row(db, daily["id"])).streak == 5
        stored = (
            (await db.execute(select(GameEvent).where(GameEvent.client_event_id == "d-1")))
            .scalar_one()
            .payload
        )
        assert stored["_outcome"]["scored"] is False
        assert "difficulty" in stored["_outcome"]["reason"]

    async def test_rejected_check_preserves_rest_of_batch(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        # The rollback must be surgical: earlier scored events keep their
        # pending rewards (profile stays dirty-unflushed between events) and
        # later events still apply — expiring shared objects would discard
        # them and 500 the batch on next access.
        daily = await _create(authenticated_async_client)
        await db.execute(
            update(Daily).where(Daily.id == daily["id"]).values(difficulty="bogus", streak=5)
        )
        await db.commit()
        response = await authenticated_async_client.post(
            f"{GAME}/events",
            json={
                "events": [
                    {
                        "client_event_id": "f-1",
                        "type": "focus_phase_completed",
                        "client_ts": _at(0).isoformat(),
                        "payload": {"minutes": 10, "difficulty": "easy"},
                    },
                    self._event("d-1", {"daily_id": daily["id"]}),
                    {
                        "client_event_id": "f-2",
                        "type": "focus_phase_completed",
                        "client_ts": _at(0).isoformat(),
                        "payload": {"minutes": 10, "difficulty": "easy"},
                    },
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["applied"] == 3
        # Both focus events' rewards persist — only the rejected check's
        # own staged state was rolled back.
        assert response.json()["profile"]["xp_today"] == 20
        assert (await _get_daily_row(db, daily["id"])).streak == 5
        marks = (
            (await db.execute(select(DailyCheck).where(DailyCheck.daily_id == daily["id"])))
            .scalars()
            .all()
        )
        assert marks == []

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

    async def test_times_per_week_impossible_first_week_not_charged(self, db: AsyncSession) -> None:
        # Anchor last Friday: its week offers only Fri–Sun = 3 check days
        # < count 4 — the first unit can never be satisfied, so it is
        # skipped; the following week still charges its miss.
        today = _today()
        friday = today - timedelta(days=(today.weekday() - 4) % 7)
        _, daily = await _make_daily(
            db,
            recurrence={"kind": "times_per_week", "count": 4},
            created_days_ago=(today - friday).days,
        )
        second_sunday = friday + timedelta(days=9)
        now = datetime.combine(second_sunday + timedelta(days=1), datetime.min.time()).replace(
            hour=4, tzinfo=timezone.utc
        )
        assert await daily_sweep.run_daily_miss_sweep(now=now) == 1
        misses = await self._miss_rows(db, daily.id)
        assert [m.scheduled_day for m in misses] == [second_sunday]

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

    async def test_freeze_window_reaches_past_lookback(self, db: AsyncSession) -> None:
        """Sparse recurrences consult 6 prior *scheduled* units — up to ~42
        days back for a weekly slot — so miss evidence must load from the
        earliest consultable unit, not just the 35-day lookback. A miss that
        far back still defeats yesterday's freeze."""
        yesterday = _today() - timedelta(days=1)
        _, daily = await _make_daily(
            db,
            created_days_ago=50,
            streak=5,
            recurrence={"kind": "weekdays", "days": [yesterday.weekday()]},
        )
        # 6 scheduled units before yesterday — beyond the old since-bound.
        old_miss_day = yesterday - timedelta(days=42)
        db.add(
            DailyMiss(
                daily_id=daily.id,
                user_id=daily.user_id,
                scheduled_day=old_miss_day,
                frozen=True,
            )
        )
        await db.commit()
        # Due units in the window: today-1, -8, -15, -22, -29.
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 5
        misses = {m.scheduled_day: m for m in await self._miss_rows(db, daily.id)}
        assert misses[yesterday].frozen is False
        assert (await _get_daily_row(db, daily.id)).streak == 0

    async def test_one_bad_daily_does_not_wedge_the_tick(self, db: AsyncSession) -> None:
        """A failing evaluation rolls back its own work and the tick moves
        on — iterating post-rollback ORM objects must not be possible (the
        expired-attribute MissingGreenlet wedge)."""
        _, bad = await _make_daily(db, created_days_ago=1, email="bad@t.dev")
        # Engine-level failure inside _evaluate_daily: unknown difficulty.
        await db.execute(update(Daily).where(Daily.id == bad.id).values(difficulty="bogus"))
        await db.commit()
        _, good = await _make_daily(db, created_days_ago=1, email="good@t.dev")
        recorded = await daily_sweep.run_daily_miss_sweep(now=_at(0, 4))
        assert recorded == 1
        # The bad daily's claim rolled back — the unit retries next tick.
        assert await self._miss_rows(db, bad.id) == []
        assert len(await self._miss_rows(db, good.id)) == 1

    async def test_claim_conflict_skips_unit_and_continues(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Losing the (daily, scheduled_day) insert race must not poison the
        tick: the claimed unit is skipped, later units still land, and the
        loser scores nothing for it. Simulates the overlap window by hiding
        a committed miss from the sweep's pre-read — the claim insert and
        its IntegrityError run for real (file-backed SQLite)."""
        _, daily = await _make_daily(db, created_days_ago=2, streak=5)
        first_day = _today() - timedelta(days=2)
        db.add(
            DailyMiss(
                daily_id=daily.id,
                user_id=daily.user_id,
                scheduled_day=first_day,
                frozen=True,
            )
        )
        await db.commit()

        async def _no_misses(db_: AsyncSession, daily_id: int, since: date) -> list:
            return []

        # The racing peer committed after our miss pre-read: the claim
        # insert is what discovers the row.
        monkeypatch.setattr(game_crud, "list_daily_misses", _no_misses)

        recorded = await daily_sweep.run_daily_miss_sweep(now=_at(0, 4))
        assert recorded == 1  # only the still-unclaimed unit
        misses = sorted(await self._miss_rows(db, daily.id), key=lambda m: m.scheduled_day)
        assert [m.scheduled_day for m in misses] == [first_day, _today() - timedelta(days=1)]
        events = await self._events(db, daily.user_id, "daily_missed")
        assert len(events) == 1  # the lost unit scored nothing
        assert (await _profile(db, daily.user_id)).hp == 48
        # The surviving unit saw the peer's miss in its freeze window —
        # unfrozen, so the streak breaks.
        assert (await _get_daily_row(db, daily.id)).streak == 0

    async def test_check_landing_mid_eval_suppresses_miss(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A check committing between the daily pre-read and the unit's
        profile lock must suppress the miss — the unit transaction re-reads
        completion under the lock before committing."""
        _, daily = await _make_daily(db, created_days_ago=1, streak=5)
        yesterday = _today() - timedelta(days=1)
        real_list = game_crud.list_daily_checks
        calls = {"n": 0}

        async def _wrapped(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                # Second call = the unit's re-read under the profile lock:
                # a check lands in a separate committed transaction
                # between the pre-read and the lock.
                from app.database import AsyncSessionLocal

                async with AsyncSessionLocal() as s:
                    s.add(
                        DailyCheck(
                            daily_id=daily.id,
                            daily_item_id=None,
                            check_date=yesterday,
                        )
                    )
                    await s.commit()
            return await real_list(*args, **kwargs)

        monkeypatch.setattr(game_crud, "list_daily_checks", _wrapped)
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 0
        assert await self._miss_rows(db, daily.id) == []
        assert (await _get_daily_row(db, daily.id)).streak == 5
        assert (await _profile(db, daily.user_id)).hp == 50

    async def test_suppressed_unit_does_not_steal_a_freeze(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A suppressed unit must not enter the freeze window: a genuine
        miss right after it still freezes the streak."""
        _, daily = await _make_daily(db, created_days_ago=2, streak=5)
        checked_day = _today() - timedelta(days=2)
        real_list = game_crud.list_daily_checks
        calls = {"n": 0}

        async def _wrapped(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                # Unit day-2's re-read: satisfaction appears between the
                # pre-read and the re-read. Staged inside the unit
                # transaction — SQLite can't model a mid-transaction
                # external commit (snapshot isolation hides it, and a
                # second writer deadlocks on the open claim insert); the
                # exercised path — re-read, suppression, missed_days
                # accounting — is identical either way.
                args[0].add(
                    DailyCheck(
                        daily_id=daily.id,
                        daily_item_id=None,
                        check_date=checked_day,
                    )
                )
                await args[0].flush()
            return await real_list(*args, **kwargs)

        monkeypatch.setattr(game_crud, "list_daily_checks", _wrapped)
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 1
        misses = await self._miss_rows(db, daily.id)
        assert len(misses) == 1
        assert misses[0].scheduled_day == _today() - timedelta(days=1)
        # The suppressed day-2 unit is not a real miss — no prior miss in
        # the rolling-7 window, so day-1 freezes instead of breaking.
        assert misses[0].frozen is True
        assert (await _get_daily_row(db, daily.id)).streak == 5
        assert (await _profile(db, daily.user_id)).hp == 48

    async def test_external_hp_change_between_units_is_not_clobbered(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A writer committing between two unit transactions must not be
        lost: the locked profile select uses populate_existing — without
        it a profile still in the identity map keeps its stale attributes
        and the second unit's HP write overwrites the external commit.

        The keep-alive wrapper holds a strong reference to the profile
        across units: the identity map is weak, so without it the object
        is collected between units and the stale read can't manifest.
        """
        _, daily = await _make_daily(db, created_days_ago=2, streak=5)
        keepalive: list[GameProfile] = []
        real_apply = engine.apply_event

        def _keepalive_apply(profile, *args, **kwargs):
            keepalive.append(profile)
            return real_apply(profile, *args, **kwargs)

        monkeypatch.setattr(engine, "apply_event", _keepalive_apply)
        real_eval = daily_sweep._evaluate_unit
        calls = {"n": 0}

        async def _wrapped(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                # Unit-1's transaction is fully committed and unit-2's
                # has not begun — an external write lands in this gap in
                # a separate committed transaction.
                from app.database import AsyncSessionLocal

                async with AsyncSessionLocal() as s:
                    prof = (
                        await s.execute(
                            select(GameProfile).where(GameProfile.user_id == daily.user_id)
                        )
                    ).scalar_one()
                    prof.hp = 40
                    await s.commit()
            return await real_eval(*args, **kwargs)

        monkeypatch.setattr(daily_sweep, "_evaluate_unit", _wrapped)
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 2
        assert len(await self._miss_rows(db, daily.id)) == 2
        # 50 -2 (unit 1) -> external 40 -> -2 (unit 2): the second loss
        # lands on the committed 40, not the stale in-memory 48.
        assert (await _profile(db, daily.user_id)).hp == 38

    async def test_recurrence_patch_is_not_retroactive(
        self, authenticated_async_client: AsyncClient, db: AsyncSession, confirmed_user: dict
    ) -> None:
        """A schedule PATCH stamps `since` on the stored blob: the lookback
        window must not re-evaluate days that ran under the old recurrence —
        pre-fix this PATCH charged ~35 retro misses (HP loss + streak wipe)."""
        daily = await _create(
            authenticated_async_client, recurrence={"kind": "weekdays", "days": [0, 2]}
        )
        # Mid-history: created 40 days ago with a real streak standing.
        await db.execute(
            update(Daily).where(Daily.id == daily["id"]).values(created_at=_at(40), streak=5)
        )
        await db.commit()
        response = await authenticated_async_client.patch(
            f"{DAILIES}/{daily['id']}", json={"recurrence": {"kind": "daily"}}
        )
        assert response.status_code == 200, response.text
        assert response.json()["recurrence"]["since"] == _today().isoformat()
        # No unit before the patch day is due under the new rule — and
        # today's unit isn't past its grace instant yet either.
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 0
        assert await self._miss_rows(db, daily["id"]) == []
        assert (await _get_daily_row(db, daily["id"])).streak == 5
        assert (await _profile(db, confirmed_user["id"])).hp == 50

    async def test_freeze_reads_misses_committed_after_snapshot(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The freeze verdict must consult misses committed through the
        profile lock, not the pre-eval snapshot: a racing instance's miss
        for a window-adjacent unit lands between our snapshot and our
        lock — scoring on the stale set would hand out a freeze the
        streak didn't earn."""
        _, daily = await _make_daily(db, created_days_ago=3, streak=5)
        # Days -3 and -2 are already satisfied, so day-1 is the only unit
        # evaluated; its rolling window spans both.
        for d in (_today() - timedelta(days=3), _today() - timedelta(days=2)):
            db.add(DailyCheck(daily_id=daily.id, daily_item_id=None, check_date=d))
        await db.commit()
        real_list = game_crud.list_daily_checks
        calls = {"n": 0}

        async def _wrapped(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                # The unit's under-lock re-read: a racing instance's day-2
                # miss commits between our miss snapshot and our claim.
                # Staged in-session — sqlite can't model a mid-transaction
                # external commit; the exercised path (post-lock miss
                # re-read -> freeze verdict) is identical either way.
                args[0].add(
                    DailyMiss(
                        daily_id=daily.id,
                        user_id=daily.user_id,
                        scheduled_day=_today() - timedelta(days=2),
                        frozen=True,
                    )
                )
                await args[0].flush()
            return await real_list(*args, **kwargs)

        monkeypatch.setattr(game_crud, "list_daily_checks", _wrapped)
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 1
        misses = {m.scheduled_day: m for m in await self._miss_rows(db, daily.id)}
        assert misses[_today() - timedelta(days=1)].frozen is False
        assert (await _get_daily_row(db, daily.id)).streak == 0

    async def test_later_committed_frozen_miss_denies_freeze(self, db: AsyncSession) -> None:
        """The freeze verdict can't be backward-only: a racing instance
        that commits a LATER unit's miss first has already spent this
        rolling window's one freeze — the earlier unit evaluating after
        must break the streak, not freeze a second miss in the window."""
        _, daily = await _make_daily(db, created_days_ago=2, streak=5)
        # Yesterday's unit is already committed frozen — as if a racing
        # instance claimed it before we got to the earlier unit.
        db.add(
            DailyMiss(
                daily_id=daily.id,
                user_id=daily.user_id,
                scheduled_day=_today() - timedelta(days=1),
                frozen=True,
            )
        )
        await db.commit()
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 1
        misses = {m.scheduled_day: m for m in await self._miss_rows(db, daily.id)}
        # Day-2's miss lands UNfrozen — yesterday's freeze already covers
        # the window it sits in.
        assert misses[_today() - timedelta(days=2)].frozen is False
        assert (await _get_daily_row(db, daily.id)).streak == 0
        assert (await _profile(db, daily.user_id)).hp == 48

    async def test_deactivation_mid_eval_suppresses_miss(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The unit re-reads `daily` under the profile lock: a PATCH
        deactivating between the pre-read and the claim bails the unit
        instead of scoring a miss on a stale active row."""
        _, daily = await _make_daily(db, created_days_ago=1, streak=5)
        real_eval = daily_sweep._evaluate_unit

        async def _wrapped(*args, **kwargs):
            # A PATCH lands between the daily pre-read and the unit txn —
            # staged in-session: visible to the under-lock re-read either
            # way, and sqlite can't model a mid-transaction external write.
            await args[0].execute(update(Daily).where(Daily.id == daily.id).values(active=False))
            return await real_eval(*args, **kwargs)

        monkeypatch.setattr(daily_sweep, "_evaluate_unit", _wrapped)
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 0
        assert await self._miss_rows(db, daily.id) == []
        assert (await _profile(db, daily.user_id)).hp == 50

    async def test_recurrence_patch_mid_eval_suppresses_miss(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A schedule PATCH landing mid-eval stamps `since` on the stored
        blob: the under-lock re-read must bail the unit instead of
        committing a miss for a day the `since` contract excludes — the
        retro-miss the stamp exists to forbid."""
        _, daily = await _make_daily(db, created_days_ago=1, streak=5)
        real_eval = daily_sweep._evaluate_unit

        async def _wrapped(*args, **kwargs):
            # The PATCH result (new schedule + today's `since`) is staged
            # in-session like the deactivation test above: visible to the
            # under-lock re-read either way, and sqlite can't model a
            # mid-transaction external write.
            await args[0].execute(
                update(Daily)
                .where(Daily.id == daily.id)
                .values(
                    recurrence={
                        "kind": "times_per_week",
                        "count": 2,
                        "since": _today().isoformat(),
                    }
                )
            )
            return await real_eval(*args, **kwargs)

        monkeypatch.setattr(daily_sweep, "_evaluate_unit", _wrapped)
        assert await daily_sweep.run_daily_miss_sweep(now=_at(0, 4)) == 0
        assert await self._miss_rows(db, daily.id) == []
        assert (await _get_daily_row(db, daily.id)).streak == 5
        assert (await _profile(db, daily.user_id)).hp == 50
