"""API tests for /api/v1/game/activity — the Stats/Activity tab feed (#66).

Covers day-score aggregation across event types, focus-minute bucketing from
phase rows vs offline-synced ledger events, empty-day fill, tier assignment,
config overrides, and streak math.
"""

import os
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 — registers every table on Base.metadata
from app.crud import game_tracking as tracking_crud
from app.game import tracking
from app.main import app
from app.models.base import Base
from app.models.game import FocusPhase, FocusSession, GameConfig, GameEvent
from app.models.user import User

ACTIVITY = "/api/v1/game/activity"
TODAY = datetime.now(timezone.utc).date()


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


def make_event(
    user_id: int, ceid: str, type_: str, ts: datetime, payload: dict | None = None
) -> GameEvent:
    return GameEvent(
        user_id=user_id,
        client_event_id=ceid,
        type=type_,
        payload=payload if payload is not None else {"_outcome": {"scored": True}},
        client_ts=ts,
    )


async def make_focus_phase(
    db_session: AsyncSession,
    user_id: int,
    day: date,
    *,
    kind: str = "focus",
    status: str = "completed",
    actual_seconds: int = 1500,
    ended_hour: int = 10,
) -> None:
    """A minimal session + phase row; phases are the scored focus unit.

    Non-completed rows keep real ended_at/actual_seconds so only the
    kind/status filters — never missing values — can exclude them.
    """
    session = FocusSession(
        user_id=user_id,
        mode="timer",
        status="ended",
        started_at=at(day, ended_hour - 1),
        ended_at=at(day, ended_hour, 30),
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        FocusPhase(
            session_id=session.id,
            seq=0,
            kind=kind,
            status=status,
            planned_seconds=actual_seconds,
            actual_seconds=actual_seconds,
            started_at=at(day, ended_hour - 1),
            ended_at=at(day, ended_hour),
        )
    )


async def second_user(async_client: AsyncClient, db: AsyncSession) -> dict:
    await async_client.post(
        "/api/v1/users/register",
        json={
            "username": "other",
            "email": "other@example.com",
            "password": "otherpassword",
        },
    )
    await db.execute(update(User).where(User.email == "other@example.com").values(confirmed=True))
    await db.commit()
    login = await async_client.post(
        "/api/v1/users/token",
        data={"username": "other@example.com", "password": "otherpassword"},
    )
    result = await db.execute(select(User).where(User.email == "other@example.com"))
    return {
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
        "id": result.scalar_one().id,
    }


def day_row(body: dict, day: date) -> dict:
    row = next(r for r in body["days"] if r["date"] == day.isoformat())
    return row


class TestActivityGrid:
    async def test_empty_user_returns_filled_zero_days(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        start = TODAY - timedelta(days=2)
        response = await authenticated_async_client.get(
            ACTIVITY, params={"start": start.isoformat(), "end": TODAY.isoformat()}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [r["date"] for r in body["days"]] == [
            (start + timedelta(days=i)).isoformat() for i in range(3)
        ]
        assert all(r["score"] == 0 and r["tier"] == 0 for r in body["days"])
        assert all(r["events"] == {} and r["focus_minutes"] == 0 for r in body["days"])
        assert body["tier_thresholds"] == [1, 15, 35, 60]

    async def test_score_aggregates_across_event_types(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        # Default weights: habit_click=2, damage=0, milestone=1. Unscored
        # lifecycle rows (session_started stamps scored:false) are excluded.
        db.add_all(
            [
                make_event(
                    confirmed_user["id"],
                    "h1",
                    "habit_click",
                    at(TODAY, 9),
                    {"_outcome": {"scored": True}},
                ),
                make_event(
                    confirmed_user["id"],
                    "h2",
                    "habit_click",
                    at(TODAY, 9, 30),
                    {"_outcome": {"scored": True}},
                ),
                make_event(
                    confirmed_user["id"],
                    "d1",
                    "damage",
                    at(TODAY, 10),
                    {"_outcome": {"scored": True, "hp_lost": 2}},
                ),
                make_event(
                    confirmed_user["id"],
                    "s1",
                    "session_started",
                    at(TODAY, 8),
                    {"_outcome": {"scored": False}},
                ),
                make_event(
                    confirmed_user["id"],
                    "m1",
                    "stopwatch_milestone",
                    at(TODAY, 11),
                    {"_outcome": {"scored": True}},
                ),
            ]
        )
        await db.commit()

        body = (
            await authenticated_async_client.get(
                ACTIVITY, params={"start": TODAY.isoformat(), "end": TODAY.isoformat()}
            )
        ).json()
        row = day_row(body, TODAY)
        assert row["events"] == {
            "habit_click": 2,
            "damage": 1,
            "stopwatch_milestone": 1,
        }
        assert row["score"] == pytest.approx(2 * 2 + 0 + 1)  # = 5 -> tier 1
        assert row["tier"] == 1

    async def test_unscored_and_forged_events_earn_no_score(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        # The mint vector: a client posts a type the engine doesn't score —
        # the row lands with _outcome.scored=false and must not earn weight.
        post = await authenticated_async_client.post(
            "/api/v1/game/events",
            json={
                "events": [
                    {
                        "client_event_id": "forge-daily",
                        "type": "daily_check",
                        "client_ts": f"{TODAY}T09:00:00Z",
                        "payload": {"daily_id": 1},
                    }
                ]
            },
        )
        assert post.status_code == 200, post.text
        db.add_all(
            [
                # Unscored habit_click — the marker the service writes for
                # unresolvable/direction-mismatched clicks.
                make_event(
                    confirmed_user["id"],
                    "h-bad",
                    "habit_click",
                    at(TODAY, 10),
                    {
                        "habit_id": 999,
                        "_outcome": {"scored": False, "reason": "habit_unresolvable"},
                    },
                ),
                make_event(
                    confirmed_user["id"],
                    "h-ok",
                    "habit_click",
                    at(TODAY, 11),
                    {"_outcome": {"scored": True}},
                ),
                # An outcome without a scored key is NOT explicit-false and
                # still counts (a forged row always lands scored:false).
                make_event(
                    confirmed_user["id"],
                    "h-legacy",
                    "habit_click",
                    at(TODAY, 12),
                    {"_outcome": {"xp": 25}},
                ),
            ]
        )
        await db.commit()

        body = (
            await authenticated_async_client.get(
                ACTIVITY, params={"start": TODAY.isoformat(), "end": TODAY.isoformat()}
            )
        ).json()
        row = day_row(body, TODAY)
        assert row["events"] == {"habit_click": 2}
        assert row["score"] == pytest.approx(4.0)

    async def test_focus_minutes_from_completed_phases(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await make_focus_phase(db, confirmed_user["id"], TODAY, actual_seconds=1500)
        # A break and an abandoned focus phase contribute nothing.
        await make_focus_phase(
            db, confirmed_user["id"], TODAY, kind="break", actual_seconds=300, ended_hour=11
        )
        await make_focus_phase(
            db, confirmed_user["id"], TODAY, status="abandoned", actual_seconds=600, ended_hour=12
        )
        await db.commit()

        body = (
            await authenticated_async_client.get(
                ACTIVITY, params={"start": TODAY.isoformat(), "end": TODAY.isoformat()}
            )
        ).json()
        row = day_row(body, TODAY)
        assert row["focus_minutes"] == pytest.approx(25.0)
        assert row["score"] == pytest.approx(25.0)  # 25 -> tier 2
        assert row["tier"] == 2

    async def test_offline_focus_event_adds_minutes_but_server_row_does_not(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        # Server-run focus: phase row 1500s + its server-authored ledger twin.
        await make_focus_phase(db, confirmed_user["id"], TODAY, actual_seconds=1500)
        db.add(
            make_event(
                confirmed_user["id"],
                "server:s9:phase_completed:0:1700000000:0",
                "focus_phase_completed",
                at(TODAY, 10),
                {"session_id": 9, "minutes": 25, "_outcome": {"scored": True}},
            )
        )
        # Offline sync: client-authored row, payload.minutes counts, weight 0.
        db.add(
            make_event(
                confirmed_user["id"],
                "client-abc",
                "focus_phase_completed",
                at(TODAY, 15),
                {"minutes": 30, "_outcome": {"scored": True}},
            )
        )
        await db.commit()

        body = (
            await authenticated_async_client.get(
                ACTIVITY, params={"start": TODAY.isoformat(), "end": TODAY.isoformat()}
            )
        ).json()
        row = day_row(body, TODAY)
        # 25 (phase row) + 30 (client payload) — NOT +25 for the server row.
        assert row["focus_minutes"] == pytest.approx(55.0)
        assert row["events"] == {"focus_phase_completed": 2}
        assert row["score"] == pytest.approx(55.0)  # weight 0 -> score is minutes only
        assert row["tier"] == 3

    async def test_server_prefix_match_is_case_insensitive(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        # SQLite LIKE is ASCII case-insensitive but PG LIKE is not — the
        # namespace split must behave identically on both backends.
        db.add(
            make_event(
                confirmed_user["id"],
                "SERVER:squat",
                "focus_phase_completed",
                at(TODAY, 9),
                {"minutes": 99, "_outcome": {"scored": True}},
            )
        )
        await db.commit()

        body = (
            await authenticated_async_client.get(
                ACTIVITY, params={"start": TODAY.isoformat(), "end": TODAY.isoformat()}
            )
        ).json()
        row = day_row(body, TODAY)
        assert row["focus_minutes"] == 0
        # The row itself still shows in the events map (weight 0 either way).
        assert row["events"] == {"focus_phase_completed": 1}

    async def test_events_bucket_by_client_ts_day(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        yesterday = TODAY - timedelta(days=1)
        db.add(make_event(confirmed_user["id"], "old", "habit_click", at(yesterday, 23, 59)))
        db.add(make_event(confirmed_user["id"], "new", "habit_click", at(TODAY, 0, 1)))
        await db.commit()

        body = (
            await authenticated_async_client.get(
                ACTIVITY,
                params={"start": yesterday.isoformat(), "end": TODAY.isoformat()},
            )
        ).json()
        assert day_row(body, yesterday)["events"] == {"habit_click": 1}
        assert day_row(body, TODAY)["events"] == {"habit_click": 1}

    async def test_activity_weights_config_overrides_defaults(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        db.add(
            GameConfig(
                key="activity_weights",
                value={
                    "weights": {"habit_click": 5},
                    "tier_thresholds": [1, 10],
                },
            )
        )
        db.add_all(
            [
                make_event(confirmed_user["id"], f"h{i}", "habit_click", at(TODAY, 9))
                for i in range(3)
            ]
        )
        await db.commit()

        body = (
            await authenticated_async_client.get(
                ACTIVITY, params={"start": TODAY.isoformat(), "end": TODAY.isoformat()}
            )
        ).json()
        row = day_row(body, TODAY)
        assert row["score"] == pytest.approx(15.0)  # 3 x 5
        assert row["tier"] == 2  # custom ladder [1, 10]
        assert body["tier_thresholds"] == [1, 10]

    async def test_focus_phase_weight_is_pinned_to_zero(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        # A config weight on focus_phase_completed can't reintroduce the
        # minutes+events double-count — the code pins it to 0.
        db.add(
            GameConfig(
                key="activity_weights",
                value={"weights": {"focus_phase_completed": 5}},
            )
        )
        db.add(
            make_event(
                confirmed_user["id"],
                "client-1",
                "focus_phase_completed",
                at(TODAY, 9),
                {"minutes": 30, "_outcome": {"scored": True}},
            )
        )
        await db.commit()

        body = (
            await authenticated_async_client.get(
                ACTIVITY, params={"start": TODAY.isoformat(), "end": TODAY.isoformat()}
            )
        ).json()
        row = day_row(body, TODAY)
        assert row["focus_minutes"] == pytest.approx(30.0)
        assert row["score"] == pytest.approx(30.0)  # not 30 + 5

    async def test_non_object_config_row_falls_back_to_defaults(
        self,
        authenticated_async_client: AsyncClient,
        db: AsyncSession,
    ) -> None:
        # JSONB holds any JSON value — a string/list row must not 500.
        db.add(GameConfig(key="activity_weights", value="bogus"))
        await db.commit()

        response = await authenticated_async_client.get(
            ACTIVITY, params={"start": TODAY.isoformat(), "end": TODAY.isoformat()}
        )
        assert response.status_code == 200, response.text
        assert response.json()["tier_thresholds"] == [1, 15, 35, 60]

    async def test_end_clamps_to_today(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        db.add(
            make_event(
                confirmed_user["id"],
                "h1",
                "habit_click",
                at(TODAY, 9),
                {"_outcome": {"scored": True}},
            )
        )
        await db.commit()
        params = {
            "start": (TODAY - timedelta(days=3)).isoformat(),
            "end": (TODAY + timedelta(days=30)).isoformat(),
        }

        body = (await authenticated_async_client.get(ACTIVITY, params=params)).json()
        assert body["end"] == TODAY.isoformat()
        assert body["days"][-1]["date"] == TODAY.isoformat()

        # A scoreless future tail can't zero the current streak.
        stats = (await authenticated_async_client.get(ACTIVITY + "/stats", params=params)).json()
        assert stats["current_streak"] == 1

    async def test_range_validation(self, authenticated_async_client: AsyncClient) -> None:
        # start after end
        response = await authenticated_async_client.get(
            ACTIVITY,
            params={"start": TODAY.isoformat(), "end": (TODAY - timedelta(days=1)).isoformat()},
        )
        assert response.status_code == 400
        # span beyond the hard cap
        response = await authenticated_async_client.get(
            ACTIVITY,
            params={
                "start": (TODAY - timedelta(days=400)).isoformat(),
                "end": TODAY.isoformat(),
            },
        )
        assert response.status_code == 400
        # extreme dates overflow the window arithmetic — 400, not 500
        for extreme in ("0001-01-01", "9999-12-31"):
            response = await authenticated_async_client.get(ACTIVITY, params={"end": extreme})
            assert response.status_code == 400, extreme

    async def test_scoped_to_user(
        self,
        authenticated_async_client: AsyncClient,
        async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        other = await second_user(async_client, db)
        db.add(make_event(other["id"], "theirs", "habit_click", at(TODAY, 9)))
        await make_focus_phase(db, other["id"], TODAY, actual_seconds=3600)
        await db.commit()

        body = (
            await authenticated_async_client.get(
                ACTIVITY, params={"start": TODAY.isoformat(), "end": TODAY.isoformat()}
            )
        ).json()
        row = day_row(body, TODAY)
        assert row["events"] == {}
        assert row["focus_minutes"] == 0
        assert row["score"] == 0

    async def test_requires_auth(self, async_client: AsyncClient) -> None:
        # Fresh client: `async_client` picks up an auth cookie at registration.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver/"
        ) as anon:
            response = await anon.get(ACTIVITY)
        assert response.status_code == 401


class TestActivityStats:
    async def _seed(self, db: AsyncSession, user_id: int, active_days: list[int]) -> None:
        """One habit_click (score 2) on each `days ago` offset in active_days."""
        db.add_all(
            make_event(
                user_id,
                f"h-{ago}",
                "habit_click",
                at(TODAY - timedelta(days=ago), 12),
            )
            for ago in active_days
        )
        await db.commit()

    async def test_stat_set_math(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        # Active streaks: today, and 3..5 days ago (broken by 2 & 1 days ago).
        await self._seed(db, confirmed_user["id"], [0, 3, 4, 5])
        await make_focus_phase(
            db, confirmed_user["id"], TODAY - timedelta(days=4), actual_seconds=3600
        )
        await db.commit()

        response = await authenticated_async_client.get(
            ACTIVITY + "/stats",
            params={
                "start": (TODAY - timedelta(days=6)).isoformat(),
                "end": TODAY.isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # scores: today=2, d-3=2, d-4=62 (60min+2), d-5=2
        assert body["current_streak"] == 1
        assert body["longest_streak"] == 3
        assert body["total_hours"] == pytest.approx(1.0)
        assert body["avg_hours_per_day"] == pytest.approx(round(1.0 / 7, 2))
        assert body["best_day"] == {
            "date": (TODAY - timedelta(days=4)).isoformat(),
            "score": 62.0,
        }
        assert body["weekly_total"] == pytest.approx(68.0)
        assert body["speedrun_pbs"] is None

    async def test_scoreless_today_does_not_break_current_streak(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._seed(db, confirmed_user["id"], [1, 2])
        body = (
            await authenticated_async_client.get(
                ACTIVITY + "/stats",
                params={
                    "start": (TODAY - timedelta(days=4)).isoformat(),
                    "end": TODAY.isoformat(),
                },
            )
        ).json()
        assert body["current_streak"] == 2
        assert body["longest_streak"] == 2

    async def test_broken_streak_reports_zero_current(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await self._seed(db, confirmed_user["id"], [3, 4])
        body = (
            await authenticated_async_client.get(
                ACTIVITY + "/stats",
                params={
                    "start": (TODAY - timedelta(days=6)).isoformat(),
                    "end": TODAY.isoformat(),
                },
            )
        ).json()
        assert body["current_streak"] == 0
        assert body["longest_streak"] == 2

    async def test_empty_stats(self, authenticated_async_client: AsyncClient) -> None:
        body = (
            await authenticated_async_client.get(
                ACTIVITY + "/stats",
                params={
                    "start": (TODAY - timedelta(days=6)).isoformat(),
                    "end": TODAY.isoformat(),
                },
            )
        ).json()
        assert body["total_hours"] == 0
        assert body["avg_hours_per_day"] == 0
        assert body["current_streak"] == 0
        assert body["longest_streak"] == 0
        assert body["best_day"] is None
        assert body["weekly_total"] == 0
        assert body["speedrun_pbs"] is None


def test_tier_computed_on_the_shipped_score() -> None:
    # 3 x 4.9999 = 14.9997 -> ships 15.0; tier must match the shipped score
    # or a client recomputing tier from score+thresholds disagrees.
    rates = tracking.ActivityRates(weights={"habit_click": 4.9999}, tier_thresholds=(1.0, 15.0))
    days = tracking.build_days(TODAY, TODAY, {}, {TODAY: {"habit_click": 3}}, rates)
    assert days[0]["score"] == 15.0
    assert days[0]["tier"] == 2


PG_URL = os.getenv("GAME_TEST_DB_URL")

# The dialect branches (AT TIME ZONE bucketing, ->> text extraction,
# jsonb_typeof, ilike) only exist on real Postgres — SQLite can't verify them.
requires_postgres = pytest.mark.skipif(
    not (PG_URL and PG_URL.startswith("postgresql")),
    reason="Postgres-only SQL paths (GAME_TEST_DB_URL not set)",
)


@requires_postgres
async def test_aggregation_queries_on_postgres() -> None:
    """Exercise the PG branches of the three aggregation queries directly."""
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as s:
            s.add(
                User(
                    username="pg-activity",
                    email=f"pg-activity-{os.urandom(4).hex()}@test.dev",
                    password="x",
                    confirmed=True,
                )
            )
            await s.commit()
            uid = (
                await s.execute(select(User.id).where(User.username == "pg-activity"))
            ).scalar_one()
            start_dt = datetime(TODAY.year, TODAY.month, TODAY.day, tzinfo=timezone.utc)
            end_dt = start_dt + timedelta(days=1)
            session = FocusSession(
                user_id=uid,
                mode="timer",
                status="ended",
                started_at=start_dt,
                ended_at=at(TODAY, 10, 30),
            )
            s.add(session)
            await s.flush()
            s.add_all(
                [
                    FocusPhase(
                        session_id=session.id,
                        seq=0,
                        kind="focus",
                        status="completed",
                        planned_seconds=1500,
                        actual_seconds=1500,
                        started_at=at(TODAY, 9),
                        ended_at=at(TODAY, 10),
                    ),
                    GameEvent(
                        user_id=uid,
                        client_event_id="pg-h1",
                        type="habit_click",
                        payload={"_outcome": {"scored": True}},
                        client_ts=at(TODAY, 9),
                    ),
                    GameEvent(
                        user_id=uid,
                        client_event_id="pg-bad",
                        type="habit_click",
                        payload={"_outcome": {"scored": False}},
                        client_ts=at(TODAY, 9),
                    ),
                    GameEvent(
                        user_id=uid,
                        client_event_id="server:s1:phase_completed:0:1:0",
                        type="focus_phase_completed",
                        payload={"minutes": 25, "_outcome": {"scored": True}},
                        client_ts=at(TODAY, 10),
                    ),
                    GameEvent(
                        user_id=uid,
                        client_event_id="pg-client",
                        type="focus_phase_completed",
                        payload={"minutes": 30, "_outcome": {"scored": True}},
                        client_ts=at(TODAY, 11),
                    ),
                ]
            )
            await s.commit()

            counts = await tracking_crud.get_event_counts_by_day(s, uid, start_dt, end_dt)
            assert counts == {TODAY: {"habit_click": 1, "focus_phase_completed": 2}}
            phase_minutes = await tracking_crud.get_focus_minutes_by_day(s, uid, start_dt, end_dt)
            assert phase_minutes == {TODAY: pytest.approx(25.0)}
            client_minutes = await tracking_crud.get_client_focus_minutes_by_day(
                s, uid, start_dt, end_dt
            )
            assert client_minutes == {TODAY: pytest.approx(30.0)}
    finally:
        await engine.dispose()
