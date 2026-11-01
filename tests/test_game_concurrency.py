"""Concurrent game-event ingestion — exercises what SQLite cannot: FOR UPDATE
row locking and the first-profile create race (rollback + re-select).

Set GAME_TEST_DB_URL to a reachable async URL; CI points it at the scratch
Postgres in the alembic job. Skipped by default so the suite stays SQLite-only;
locally any URL works for a smoke run (e.g. sqlite+aiosqlite:///./conc.db).
"""

import asyncio
import os
import random
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 — registers every table on Base.metadata
from app.game import service
from app.models.base import Base
from app.models.game import GameEvent, GameProfile, Habit
from app.models.user import User
from app.schemas.game import GameEventIn

DB_URL = os.getenv("GAME_TEST_DB_URL")

pytestmark = pytest.mark.skipif(not DB_URL, reason="GAME_TEST_DB_URL not set")

# SQLite has no row locks — FOR UPDATE is a no-op and concurrent
# read-modify-write loses updates by design. Only Postgres can satisfy the
# serialized-totals contract, so that case is PG-gated.
requires_postgres = pytest.mark.skipif(
    not (DB_URL and DB_URL.startswith("postgresql")),
    reason="row-lock serialization needs Postgres",
)


def ev(client_event_id: str, minutes: int) -> GameEventIn:
    return GameEventIn(
        client_event_id=client_event_id,
        type="focus_phase_completed",
        client_ts=datetime.now(timezone.utc),
        payload={"minutes": minutes, "difficulty": "easy"},
    )


@pytest.fixture()
async def sessions():
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _ingest(Session, user_id: int, events: list[GameEventIn], attempts: int = 5) -> None:
    """Ingest on a dedicated session. A lost race surfaces as IntegrityError
    (unique client_event_id) or a lock error; the retry IS the idempotent path
    real clients take."""
    for attempt in range(attempts):
        async with Session() as s:
            try:
                # Seeded so no crit ever rolls (0.84 > 0.03 chance) — XP
                # assertions stay deterministic across runs and backends.
                await service.ingest_events(s, user_id, events, rng=random.Random(0))
                await s.commit()
                return
            except (IntegrityError, OperationalError):
                await s.rollback()
                if attempt == attempts - 1:
                    raise


async def _make_user(Session, email: str) -> int:
    # Per-run suffix: reruns against a persistent GAME_TEST_DB_URL must not
    # collide on users.email.
    email = f"{email.split('@')[0]}-{uuid4().hex[:8]}@test.dev"
    async with Session() as s:
        user = User(username=email.split("@")[0], email=email, password="x", confirmed=True)
        s.add(user)
        await s.commit()
        return user.id


async def _fetch(Session, user_id: int):
    async with Session() as s:
        ids = sorted(
            (
                await s.execute(
                    select(GameEvent.client_event_id).where(GameEvent.user_id == user_id)
                )
            ).scalars()
        )
        profile = (
            await s.execute(select(GameProfile).where(GameProfile.user_id == user_id))
        ).scalar_one()
        return ids, profile


async def test_concurrent_first_ingest_race(sessions):
    """Both batches arrive before the profile exists: the loser hits the
    user_id unique constraint, recovers via rollback+reselect under FOR UPDATE,
    and dedupes against the winner's committed events."""
    uid = await _make_user(sessions, "race-a@test.dev")
    batch_a = [ev("e-1", 10), ev("e-2", 15)]
    batch_b = [ev("e-1", 10), ev("e-3", 20)]  # e-1 overlaps
    await asyncio.gather(
        _ingest(sessions, uid, batch_a),
        _ingest(sessions, uid, batch_b),
    )
    ids, profile = await _fetch(sessions, uid)
    assert ids == ["e-1", "e-2", "e-3"]  # overlap persisted exactly once
    assert profile.xp_today == 45  # (10+15+20) min * 1 xp/min — no double-count


@requires_postgres
async def test_concurrent_ingest_no_lost_update(sessions):
    """FOR UPDATE serializes batches on an existing profile: both commits land
    and totals are additive, not last-writer-wins."""
    uid = await _make_user(sessions, "race-b@test.dev")
    await _ingest(sessions, uid, [ev("e-0", 10)])  # profile now exists
    await asyncio.gather(
        _ingest(sessions, uid, [ev("e-4", 25)]),
        _ingest(sessions, uid, [ev("e-5", 35)]),
    )
    ids, profile = await _fetch(sessions, uid)
    assert ids == ["e-0", "e-4", "e-5"]
    assert profile.xp_today == 70


def _habit_click(eid: str, habit_id: int) -> GameEventIn:
    return GameEventIn(
        client_event_id=eid,
        type="habit_click",
        client_ts=datetime.now(timezone.utc),
        payload={"habit_id": habit_id, "direction": "positive"},
    )


async def _make_habit(Session, user_id: int) -> int:
    async with Session() as s:
        s.add(Habit(user_id=user_id, title="h"))
        await s.commit()
        return (await s.execute(select(Habit.id))).scalar_one()


async def test_concurrent_same_eid_habit_click(sessions):
    """Same client_event_id racing in two batches: one applies, one dedupes —
    the ledger row, counter and drift land exactly once."""
    uid = await _make_user(sessions, "race-h1@test.dev")
    hid = await _make_habit(sessions, uid)
    await asyncio.gather(
        _ingest(sessions, uid, [_habit_click("h-1", hid)]),
        _ingest(sessions, uid, [_habit_click("h-1", hid)]),
    )
    async with sessions() as s:
        rows = (
            (await s.execute(select(GameEvent).where(GameEvent.type == "habit_click")))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        habit = (await s.execute(select(Habit).where(Habit.id == hid))).scalar_one()
        assert habit.counter == 1
        assert habit.value == pytest.approx(1.0)


@requires_postgres
async def test_concurrent_habit_clicks_serialize(sessions):
    """Different eids on the same habit: the profile lock serializes them —
    both apply, counter +2, drift compounds instead of lost-updating."""
    uid = await _make_user(sessions, "race-h2@test.dev")
    hid = await _make_habit(sessions, uid)
    await asyncio.gather(
        _ingest(sessions, uid, [_habit_click("h-a", hid)]),
        _ingest(sessions, uid, [_habit_click("h-b", hid)]),
    )
    async with sessions() as s:
        rows = (
            (await s.execute(select(GameEvent).where(GameEvent.type == "habit_click")))
            .scalars()
            .all()
        )
        assert len(rows) == 2
        habit = (await s.execute(select(Habit).where(Habit.id == hid))).scalar_one()
        assert habit.counter == 2
        # 1 + 0.9747**1: second click drifted from the first's write-back.
        assert habit.value == pytest.approx(1.0 + 0.9747**1.0, abs=1e-6)
