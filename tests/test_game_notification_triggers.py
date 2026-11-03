"""Trigger-hook tests for the notification pillar (#68) — the scoring call
sites that emit warnings/celebrations/alerts. Dispatch internals live in
test_game_notifications.py.
"""

import random
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.game import achievements, daily_sweep, notifications, service
from app.models.game import GameProfile
from app.models.notification import NotificationType
from app.schemas.game import GameEventIn
from tests.test_game_notifications import _daily, _make_user, _notifs, _pref


@pytest.fixture(autouse=True)
def _mock_senders(mocker) -> dict[str, AsyncMock]:
    """Cut the real webpush/email senders; assert on these spies instead."""
    return {
        "push": mocker.patch("app.tasks._send_push_notification_async", new=AsyncMock()),
        "email": mocker.patch("app.tasks._send_confirmation_email_async", new=AsyncMock()),
    }


@pytest.mark.anyio
async def test_daily_miss_sweep_emits_daily_missed(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """A checked-day daily left unchecked past grace notifies via the sweep."""
    user = await _make_user(db)
    db.add(GameProfile(user_id=user.id))
    # Created yesterday -> yesterday is the only due unit at 04:00 today.
    db.add(_daily(user.id, created_at=datetime.now(timezone.utc) - timedelta(days=1)))
    await db.commit()
    # 04:00 UTC — yesterday's unit is past day-end + 3h grace.
    now = datetime.now(timezone.utc).replace(hour=4, minute=0, second=0, microsecond=0)

    assert await daily_sweep.run_daily_miss_sweep(now=now) == 1
    rows = await _notifs(db, user.id, NotificationType.DAILY_MISSED)
    assert len(rows) == 1
    assert rows[0].meta["daily_id"] is not None


@pytest.mark.anyio
async def test_low_hp_only_on_downward_crossing(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    profile = GameProfile(user_id=user.id, hp=10.0, max_hp=50.0)
    db.add(profile)
    await db.flush()

    # Above -> below 12.5 (25% of 50): fires.
    await notifications.notify_score_outcome(
        db, user.id, profile, hp_before=14.0, outcome={"hp_lost": 2.0}
    )
    await db.flush()
    assert len(await _notifs(db, user.id, NotificationType.LOW_HP)) == 1

    # Below -> below: no repeat.
    await notifications.notify_score_outcome(
        db, user.id, profile, hp_before=10.0, outcome={"hp_lost": 2.0}
    )
    await db.flush()
    assert len(await _notifs(db, user.id, NotificationType.LOW_HP)) == 1


@pytest.mark.anyio
async def test_death_emits_death_never_low_hp(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    profile = GameProfile(user_id=user.id, hp=0.0, max_hp=50.0)
    db.add(profile)
    await db.flush()

    await notifications.notify_score_outcome(
        db, user.id, profile, hp_before=5.0, outcome={"died": True, "hp_lost": 5.0}
    )
    await db.flush()

    assert len(await _notifs(db, user.id, NotificationType.DEATH)) == 1
    assert await _notifs(db, user.id, NotificationType.LOW_HP) == []


@pytest.mark.anyio
async def test_sweep_death_path_emits_death(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """Real path: a 1-hp profile missed daily kills — DEATH, not LOW_HP."""
    user = await _make_user(db)
    db.add(GameProfile(user_id=user.id, hp=1.0))
    db.add(_daily(user.id, created_at=datetime.now(timezone.utc) - timedelta(days=1)))
    await db.commit()
    now = datetime.now(timezone.utc).replace(hour=4, minute=0, second=0, microsecond=0)

    assert await daily_sweep.run_daily_miss_sweep(now=now) == 1
    assert len(await _notifs(db, user.id, NotificationType.DEATH)) == 1
    assert len(await _notifs(db, user.id, NotificationType.DAILY_MISSED)) == 1
    assert await _notifs(db, user.id, NotificationType.LOW_HP) == []


@pytest.mark.anyio
async def test_level_up_notification(db: AsyncSession, _mock_senders: dict[str, AsyncMock]) -> None:
    user = await _make_user(db)
    profile = GameProfile(user_id=user.id, level=6)
    db.add(profile)
    await db.flush()

    await notifications.notify_score_outcome(
        db, user.id, profile, hp_before=50.0, outcome={"levels_gained": 1}
    )
    await db.flush()

    rows = await _notifs(db, user.id, NotificationType.LEVEL_UP)
    assert len(rows) == 1
    assert "6" in rows[0].message


@pytest.mark.anyio
async def test_achievement_grants_emit_one_notification_each(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """evaluate() grants -> one ACHIEVEMENT feed row per grant."""
    user = await _make_user(db)
    profile = GameProfile(user_id=user.id, level=10)
    db.add(profile)
    await db.flush()

    granted = await achievements.evaluate(db, user.id, profile)
    await db.commit()

    assert any(a.key == "level-10" for a in granted)
    rows = await _notifs(db, user.id, NotificationType.ACHIEVEMENT)
    assert len(rows) == len(granted) >= 1
    assert {r.meta["achievement_key"] for r in rows} == {a.key for a in granted}


@pytest.mark.anyio
async def test_live_phase_end_fires_quiet_exempt(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    await _pref(db, user.id)  # 22:00–08:00 UTC quiet window
    now = datetime(2026, 5, 15, 23, 0, tzinfo=timezone.utc)  # inside quiet

    await notifications.notify_phase_end(db, user.id, client_ts=now, minutes=25, now=now)
    await db.flush()

    rows = await _notifs(db, user.id, NotificationType.PHASE_END)
    assert len(rows) == 1
    _mock_senders["push"].assert_called_once()  # timer alerts exempt


@pytest.mark.anyio
async def test_stale_phase_end_does_not_fire(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    stale = now - timedelta(minutes=10)  # beyond the 2-minute live window

    await notifications.notify_phase_end(db, user.id, client_ts=stale, minutes=25, now=now)

    assert await _notifs(db, user.id, NotificationType.PHASE_END) == []
    _mock_senders["push"].assert_not_called()


@pytest.mark.anyio
async def test_ingest_live_phase_end_notifies_stale_does_not(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """End-to-end through /game/events scoring — the offline-replay guard."""
    user = await _make_user(db)
    db.add(GameProfile(user_id=user.id))
    await db.commit()
    now = datetime.now(timezone.utc)

    live = GameEventIn(
        client_event_id="c1",
        type="focus_phase_completed",
        client_ts=now,
        payload={"minutes": 25, "difficulty": "easy"},
    )
    await service.ingest_events(db, user.id, [live], rng=random.Random(0))
    await db.flush()
    assert len(await _notifs(db, user.id, NotificationType.PHASE_END)) == 1

    stale = GameEventIn(
        client_event_id="c2",
        type="focus_phase_completed",
        client_ts=now - timedelta(hours=3),
        payload={"minutes": 25, "difficulty": "easy"},
    )
    await service.ingest_events(db, user.id, [stale], rng=random.Random(0))
    await db.flush()
    # Scored (offline replay is valid) but not alerted.
    assert len(await _notifs(db, user.id, NotificationType.PHASE_END)) == 1


@pytest.mark.anyio
async def test_notification_failure_never_breaks_scoring(db: AsyncSession, mocker: Any) -> None:
    user = await _make_user(db)
    profile = GameProfile(user_id=user.id)
    db.add(profile)
    await db.flush()
    mocker.patch.object(
        notifications, "dispatch_notification", new=AsyncMock(side_effect=RuntimeError("boom"))
    )

    # notify_score_outcome swallows the dispatch failure by contract.
    await notifications.notify_score_outcome(
        db, user.id, profile, hp_before=50.0, outcome={"levels_gained": 2}
    )
