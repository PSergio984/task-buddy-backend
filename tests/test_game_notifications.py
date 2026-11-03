"""Tests for the notification pillar — prefs matrix, quiet hours, triggers (#68).

Sender calls are mocked at the tasks.py boundary (the same seams the suite
already patches); everything between the trigger and the sender runs for real
against the SQLite test DB.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as game_crud
from app.game import notifications
from app.models.game import (
    Daily,
    DailyCheck,
    GameDeviceToken,
    GameNotificationPref,
    Habit,
)
from app.models.notification import Notification, NotificationType
from app.models.user import User
from tests.conftest import TestSessionLocal

GAME = "/api/v1/game"
PREFS_URL = f"{GAME}/notification-prefs"
TOKENS_URL = f"{GAME}/device-tokens"
READ_ALL_URL = "/api/v1/notifications/read-all"

MANILA = "Asia/Manila"  # fixed UTC+8, no DST — deterministic offset math


@pytest.fixture(autouse=True)
def _mock_senders(mocker) -> dict[str, AsyncMock]:
    """Cut the real webpush/email senders; assert on these spies instead."""
    return {
        "push": mocker.patch("app.tasks._send_push_notification_async", new=AsyncMock()),
        "email": mocker.patch("app.tasks._send_confirmation_email_async", new=AsyncMock()),
    }


async def _make_user(db: AsyncSession, email: str = "notif@t.dev") -> User:
    user = User(username=email.split("@")[0], email=email, password="x", confirmed=True)
    db.add(user)
    await db.flush()
    return user


async def _pref(
    db: AsyncSession,
    user_id: int,
    *,
    prefs: dict | None = None,
    quiet: dict | None = None,
) -> GameNotificationPref:
    row = GameNotificationPref(
        user_id=user_id,
        prefs=prefs or {},
        quiet_hours=quiet if quiet is not None else dict(notifications.DEFAULT_QUIET),
    )
    db.add(row)
    await db.flush()
    return row


async def _notifs(
    db: AsyncSession, user_id: int, kind: NotificationType | None = None
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if kind is not None:
        stmt = stmt.where(Notification.type == kind)
    return list((await db.execute(stmt)).scalars().all())


async def _drain_sends() -> None:
    """Let detached sender tasks finish — dispatch fires them off-transaction
    (asyncio.create_task), so send assertions must await the module set."""
    if notifications._send_tasks:
        await asyncio.gather(*list(notifications._send_tasks))


def _habit(user_id: int, **kw) -> Habit:
    return Habit(user_id=user_id, title="Drink water", **kw)


def _daily(user_id: int, **kw) -> Daily:
    kw.setdefault("recurrence", {"kind": "daily"})
    return Daily(user_id=user_id, title="Meditate", **kw)


# --- Quiet-hours gate -------------------------------------------------------


@pytest.mark.anyio
async def test_quiet_window_suppresses_channels_but_keeps_feed_row(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    await _pref(db, user.id, quiet={"start": "22:00", "end": "08:00", "timezone": "UTC"})
    now = datetime(2026, 5, 15, 23, 30, tzinfo=timezone.utc)  # inside 22–08

    await notifications.dispatch_notification(
        db, user.id, NotificationType.LOW_HP, "t", "m", now=now
    )
    await db.commit()

    _mock_senders["push"].assert_not_called()
    _mock_senders["email"].assert_not_called()
    rows = await _notifs(db, user.id, NotificationType.LOW_HP)
    assert len(rows) == 1  # the feed row always lands — quiet gates noise, not data


@pytest.mark.anyio
async def test_outside_quiet_window_sends(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    await _pref(db, user.id)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)  # noon UTC, outside 22–08

    await notifications.dispatch_notification(
        db, user.id, NotificationType.LOW_HP, "t", "m", now=now
    )
    await _drain_sends()

    _mock_senders["push"].assert_called_once()


@pytest.mark.anyio
async def test_exempt_notification_bypasses_quiet(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    await _pref(db, user.id)
    now = datetime(2026, 5, 15, 23, 30, tzinfo=timezone.utc)

    await notifications.dispatch_notification(
        db, user.id, NotificationType.PHASE_END, "t", "m", exempt_quiet=True, now=now
    )
    await _drain_sends()

    _mock_senders["push"].assert_called_once()


@pytest.mark.anyio
async def test_quiet_window_honors_pref_timezone(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """15:00 UTC = 23:00 Manila — inside the 22–08 window only via the tz."""
    user = await _make_user(db)
    pref = await _pref(db, user.id, quiet={"start": "22:00", "end": "08:00", "timezone": MANILA})
    now = datetime(2026, 5, 15, 15, 0, tzinfo=timezone.utc)

    await notifications.dispatch_notification(
        db, user.id, NotificationType.LOW_HP, "t", "m", now=now
    )
    _mock_senders["push"].assert_not_called()

    # Same instant, UTC window — 15:00 is outside 22–08.
    pref.quiet_hours = dict(notifications.DEFAULT_QUIET)
    await db.flush()
    await notifications.dispatch_notification(
        db, user.id, NotificationType.LOW_HP, "t", "m", now=now
    )
    await _drain_sends()
    _mock_senders["push"].assert_called_once()


def test_in_quiet_window_boundaries() -> None:
    blob = {"start": "22:00", "end": "08:00", "timezone": "UTC"}
    assert notifications.in_quiet_window(blob, datetime(2026, 5, 15, 22, 0, tzinfo=timezone.utc))
    assert notifications.in_quiet_window(blob, datetime(2026, 5, 15, 7, 59, tzinfo=timezone.utc))
    assert not notifications.in_quiet_window(blob, datetime(2026, 5, 15, 8, 0, tzinfo=timezone.utc))
    # Degenerate/malformed windows gate nothing.
    assert not notifications.in_quiet_window(
        {"start": "00:00", "end": "00:00", "timezone": "UTC"},
        datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
    )
    assert not notifications.in_quiet_window(
        {"start": "soon", "end": "08:00"},
        datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
    )


# --- Channel matrix ----------------------------------------------------------


@pytest.mark.anyio
async def test_disabled_channel_skipped(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    await _pref(db, user.id, prefs={"low_hp": {"push": False}})
    now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)

    await notifications.dispatch_notification(
        db, user.id, NotificationType.LOW_HP, "t", "m", now=now
    )
    await db.flush()  # autoflush is off — pending feed rows need a flush to be visible

    _mock_senders["push"].assert_not_called()
    assert len(await _notifs(db, user.id, NotificationType.LOW_HP)) == 1


@pytest.mark.anyio
async def test_disabled_in_app_writes_no_row(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    await _pref(db, user.id, prefs={"low_hp": {"in_app": False}})

    await notifications.dispatch_notification(
        db,
        user.id,
        NotificationType.LOW_HP,
        "t",
        "m",
        now=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
    )
    await db.commit()

    assert await _notifs(db, user.id, NotificationType.LOW_HP) == []


@pytest.mark.anyio
async def test_defaults_used_without_pref_row(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """No prefs row: in_app + push on, email off — the dispatch defaults."""
    user = await _make_user(db)
    await notifications.dispatch_notification(
        db,
        user.id,
        NotificationType.LEVEL_UP,
        "t",
        "m",
        now=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
    )
    await db.flush()
    await _drain_sends()

    _mock_senders["push"].assert_called_once()
    _mock_senders["email"].assert_not_called()
    assert len(await _notifs(db, user.id, NotificationType.LEVEL_UP)) == 1


@pytest.mark.anyio
async def test_email_channel_sends_via_detached_task(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """matrix email:true invokes the Brevo sender — detached, with the
    recipient resolved on the send task's own session."""
    user = await _make_user(db)
    await _pref(db, user.id, prefs={"low_hp": {"email": True}})
    await db.commit()  # the detached task reads the user on its own session

    await notifications.dispatch_notification(
        db,
        user.id,
        NotificationType.LOW_HP,
        "title",
        "body",
        now=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
    )
    await _drain_sends()

    _mock_senders["email"].assert_awaited_once()
    assert _mock_senders["email"].call_args.args[0] == user.email


# --- Reminder tick -----------------------------------------------------------


@pytest.mark.anyio
async def test_habit_reminder_fires_at_matching_local_time(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    # Manila tz makes local 07:30 == 23:30 UTC of the previous day.
    await _pref(db, user.id, quiet={**notifications.DEFAULT_QUIET, "timezone": MANILA})
    db.add(_habit(user.id, reminder_times=["07:30", "21:00"]))
    await db.commit()
    now = datetime(2026, 5, 14, 23, 30, tzinfo=timezone.utc)  # Manila 05-15 07:30

    sent = await notifications.run_reminder_tick(now=now, session_factory=TestSessionLocal)

    assert sent == 1
    rows = await _notifs(db, user.id, NotificationType.HABIT_REMINDER)
    assert len(rows) == 1
    assert rows[0].meta["day"] == "2026-05-15"
    assert rows[0].meta["time"] == "07:30"


@pytest.mark.anyio
async def test_reminder_tick_dedupes_across_ticks(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    db.add(_habit(user.id, reminder_times=["07:30"]))
    await db.commit()
    now = datetime(2026, 5, 15, 7, 30, tzinfo=timezone.utc)  # UTC pref tz

    assert await notifications.run_reminder_tick(now=now, session_factory=TestSessionLocal) == 1
    # A second 60s tick in the same minute must not re-deliver.
    assert (
        await notifications.run_reminder_tick(
            now=now + timedelta(seconds=40), session_factory=TestSessionLocal
        )
        == 0
    )
    assert len(await _notifs(db, user.id, NotificationType.HABIT_REMINDER)) == 1


@pytest.mark.anyio
async def test_daily_reminder_skips_unscheduled_day(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """Reminder time matches, but the recurrence doesn't schedule today."""
    user = await _make_user(db)
    # 2026-05-15 is a Friday — a Monday/Wednesday daily stays quiet.
    db.add(
        _daily(
            user.id,
            recurrence={"kind": "weekdays", "days": [0, 2]},
            reminder_times=["07:30"],
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
    )
    await db.commit()
    now = datetime(2026, 5, 15, 7, 30, tzinfo=timezone.utc)

    sent = await notifications.run_reminder_tick(now=now, session_factory=TestSessionLocal)

    assert sent == 0
    assert await _notifs(db, user.id, NotificationType.DAILY_REMINDER) == []


@pytest.mark.anyio
async def test_daily_reminder_fires_when_scheduled(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    db.add(
        _daily(
            user.id,
            recurrence={"kind": "weekdays", "days": [4]},  # Friday
            reminder_times=["07:30"],
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
    )
    await db.commit()
    now = datetime(2026, 5, 15, 7, 30, tzinfo=timezone.utc)

    assert await notifications.run_reminder_tick(now=now, session_factory=TestSessionLocal) == 1
    assert len(await _notifs(db, user.id, NotificationType.DAILY_REMINDER)) == 1


@pytest.mark.anyio
async def test_streak_risk_fires_once_per_local_day(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    db.add(_daily(user.id, created_at=datetime(2026, 5, 1, tzinfo=timezone.utc)))
    await db.commit()
    now = datetime(2026, 5, 15, 20, 30, tzinfo=timezone.utc)  # local hour 20

    assert await notifications.run_reminder_tick(now=now, session_factory=TestSessionLocal) == 1
    assert (
        await notifications.run_reminder_tick(
            now=now + timedelta(minutes=10), session_factory=TestSessionLocal
        )
        == 0
    )
    rows = await _notifs(db, user.id, NotificationType.STREAK_RISK)
    assert len(rows) == 1
    assert rows[0].meta["day"] == "2026-05-15"


@pytest.mark.anyio
async def test_streak_risk_silent_when_all_checked(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    user = await _make_user(db)
    daily = _daily(user.id, created_at=datetime(2026, 5, 1, tzinfo=timezone.utc))
    db.add(daily)
    await db.flush()
    db.add(DailyCheck(daily_id=daily.id, check_date=date(2026, 5, 15), done=True))
    await db.commit()
    now = datetime(2026, 5, 15, 20, 30, tzinfo=timezone.utc)

    sent = await notifications.run_reminder_tick(now=now, session_factory=TestSessionLocal)

    assert sent == 0
    assert await _notifs(db, user.id, NotificationType.STREAK_RISK) == []


@pytest.mark.anyio
async def test_daily_reminder_skips_when_checked_today(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """A 07:00 check must not still get the 07:30 reminder — today's marks
    are loaded once per user and a checked daily stays quiet."""
    user = await _make_user(db)
    daily = _daily(
        user.id,
        reminder_times=["07:30"],
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    db.add(daily)
    await db.flush()
    db.add(DailyCheck(daily_id=daily.id, check_date=date(2026, 5, 15), done=True))
    await db.commit()

    sent = await notifications.run_reminder_tick(
        now=datetime(2026, 5, 15, 7, 30, tzinfo=timezone.utc),
        session_factory=TestSessionLocal,
    )

    assert sent == 0
    assert await _notifs(db, user.id, NotificationType.DAILY_REMINDER) == []


@pytest.mark.anyio
async def test_times_per_week_quota_met_stays_quiet(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """A 1x/week daily checked this week: no reminder at its time and no
    streak-risk listing — the week's quota is met; the deadline is Sunday."""
    user = await _make_user(db)
    daily = _daily(
        user.id,
        recurrence={"kind": "times_per_week", "count": 1},
        reminder_times=["07:30"],
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    db.add(daily)
    await db.flush()
    # Tuesday of the same ISO week (Mon 05-11 .. Sun 05-17) — quota met.
    db.add(DailyCheck(daily_id=daily.id, check_date=date(2026, 5, 12), done=True))
    await db.commit()

    # Friday 07:30 local — the reminder time matches but the week is done.
    assert (
        await notifications.run_reminder_tick(
            now=datetime(2026, 5, 15, 7, 30, tzinfo=timezone.utc),
            session_factory=TestSessionLocal,
        )
        == 0
    )
    # Local 20:00 — a satisfied week must not list in streak-risk either.
    assert (
        await notifications.run_reminder_tick(
            now=datetime(2026, 5, 15, 20, 30, tzinfo=timezone.utc),
            session_factory=TestSessionLocal,
        )
        == 0
    )
    assert await _notifs(db, user.id, NotificationType.DAILY_REMINDER) == []
    assert await _notifs(db, user.id, NotificationType.STREAK_RISK) == []


@pytest.mark.anyio
async def test_times_per_week_unsatisfied_still_reminds(
    db: AsyncSession, _mock_senders: dict[str, AsyncMock]
) -> None:
    """Same daily with the quota open: the reminder fires and the 20:00
    tick lists it in streak-risk — last week's check doesn't count."""
    user = await _make_user(db)
    daily = _daily(
        user.id,
        recurrence={"kind": "times_per_week", "count": 2},
        reminder_times=["07:30"],
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    db.add(daily)
    await db.flush()
    # One this week (Tue) + one last week — count=2 stays open.
    db.add(DailyCheck(daily_id=daily.id, check_date=date(2026, 5, 12), done=True))
    db.add(DailyCheck(daily_id=daily.id, check_date=date(2026, 5, 8), done=True))
    await db.commit()

    assert (
        await notifications.run_reminder_tick(
            now=datetime(2026, 5, 15, 7, 30, tzinfo=timezone.utc),
            session_factory=TestSessionLocal,
        )
        == 1
    )
    assert len(await _notifs(db, user.id, NotificationType.DAILY_REMINDER)) == 1

    assert (
        await notifications.run_reminder_tick(
            now=datetime(2026, 5, 15, 20, 30, tzinfo=timezone.utc),
            session_factory=TestSessionLocal,
        )
        == 1
    )
    rows = await _notifs(db, user.id, NotificationType.STREAK_RISK)
    assert len(rows) == 1
    assert "Meditate" in rows[0].message


# --- Prefs endpoints ---------------------------------------------------------


@pytest.mark.anyio
async def test_get_prefs_returns_defaults(authenticated_async_client: AsyncClient) -> None:
    response = await authenticated_async_client.get(PREFS_URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["quiet_hours"] == {"start": "22:00", "end": "08:00", "timezone": "UTC"}
    assert set(body["prefs"]) == notifications.KIND_KEYS
    assert body["prefs"]["low_hp"] == {"in_app": True, "push": True, "email": False}


@pytest.mark.anyio
async def test_put_prefs_roundtrip(authenticated_async_client: AsyncClient) -> None:
    body = {
        "prefs": {"low_hp": {"push": False, "email": True}},
        "quiet_hours": {"start": "23:00", "end": "07:30", "timezone": MANILA},
    }
    response = await authenticated_async_client.put(PREFS_URL, json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["prefs"]["low_hp"] == {"in_app": True, "push": False, "email": True}
    assert saved["quiet_hours"]["timezone"] == MANILA

    # Persisted: a fresh GET returns the same effective matrix.
    again = await authenticated_async_client.get(PREFS_URL)
    assert again.json() == saved


@pytest.mark.anyio
async def test_put_unknown_kind_rejected(authenticated_async_client: AsyncClient) -> None:
    response = await authenticated_async_client.put(
        PREFS_URL, json={"prefs": {"bogus_kind": {"push": True}}}
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_put_unknown_channel_rejected(authenticated_async_client: AsyncClient) -> None:
    response = await authenticated_async_client.put(
        PREFS_URL, json={"prefs": {"low_hp": {"carrier_pigeon": True}}}
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_put_invalid_quiet_hours_rejected(authenticated_async_client: AsyncClient) -> None:
    for quiet in (
        {"start": "25:00", "end": "08:00"},
        {"start": "22:00", "end": "8pm"},
        {"start": "22:00", "end": "08:00", "timezone": "Mars/Olympus"},
    ):
        response = await authenticated_async_client.put(PREFS_URL, json={"quiet_hours": quiet})
        assert response.status_code == 422, quiet


@pytest.mark.anyio
async def test_put_non_bool_channel_rejected(authenticated_async_client: AsyncClient) -> None:
    response = await authenticated_async_client.put(
        PREFS_URL, json={"prefs": {"low_hp": {"push": "yes"}}}
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_put_rejects_unknown_top_level_key(
    authenticated_async_client: AsyncClient,
) -> None:
    """extra='forbid': a `quite_hours` typo must 422, not silently drop."""
    response = await authenticated_async_client.put(
        PREFS_URL, json={"quite_hours": {"start": "23:00", "end": "07:00"}}
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_get_prefs_corrupt_stored_blobs_return_defaults(
    authenticated_async_client: AsyncClient, confirmed_user: dict, db: AsyncSession
) -> None:
    """Out-of-band writes can store shapes PUT would reject — reads collapse
    them to the default matrix, never a 500."""
    pref = GameNotificationPref(
        user_id=confirmed_user["id"],
        prefs={"low_hp": "off"},  # truthy non-dict kind value
        quiet_hours="nope",  # non-dict quiet blob
    )
    db.add(pref)
    await db.commit()

    response = await authenticated_async_client.get(PREFS_URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["prefs"]) == notifications.KIND_KEYS
    assert body["prefs"]["low_hp"] == {"in_app": True, "push": True, "email": False}
    assert body["quiet_hours"] == {"start": "22:00", "end": "08:00", "timezone": "UTC"}

    # Non-bool channel value and unknown channel key — same collapse.
    pref.quiet_hours = {}
    for blob in ({"low_hp": {"push": "yes"}}, {"streak_risk": {"carrier_pigeon": True}}):
        pref.prefs = blob
        await db.commit()
        response = await authenticated_async_client.get(PREFS_URL)
        assert response.status_code == 200, response.text
        assert response.json()["prefs"]["low_hp"] == {
            "in_app": True,
            "push": True,
            "email": False,
        }


# --- Device-token endpoints ---------------------------------------------------


@pytest.mark.anyio
async def test_device_token_register_and_upsert(
    authenticated_async_client: AsyncClient, confirmed_user: dict, db: AsyncSession
) -> None:
    body = {"platform": "expo", "token": "ExponentPushToken[abc]"}
    first = await authenticated_async_client.post(TOKENS_URL, json=body)
    assert first.status_code == 201, first.text
    again = await authenticated_async_client.post(TOKENS_URL, json=body)
    assert again.status_code == 201
    assert first.json()["id"] == again.json()["id"]  # upsert, not duplicate


@pytest.mark.anyio
async def test_device_token_upsert_reassigns_ownership(
    authenticated_async_client: AsyncClient, db: AsyncSession
) -> None:
    """A token already bound to another account transfers to the caller —
    same claim pattern as the webpush endpoint upsert."""
    other = await _make_user(db, "other@t.dev")
    db.add(GameDeviceToken(user_id=other.id, platform="expo", token="tok-1"))
    await db.commit()

    response = await authenticated_async_client.post(
        TOKENS_URL, json={"platform": "expo", "token": "tok-1"}
    )
    assert response.status_code == 201
    row = (
        await db.execute(select(GameDeviceToken).where(GameDeviceToken.token == "tok-1"))
    ).scalar_one()
    assert row.user_id != other.id


@pytest.mark.anyio
async def test_device_token_delete(
    authenticated_async_client: AsyncClient, confirmed_user: dict, db: AsyncSession
) -> None:
    await authenticated_async_client.post(TOKENS_URL, json={"platform": "expo", "token": "tok-del"})
    response = await authenticated_async_client.delete(f"{TOKENS_URL}/tok-del")
    assert response.status_code == 204
    assert (
        await db.execute(select(GameDeviceToken).where(GameDeviceToken.token == "tok-del"))
    ).scalar_one_or_none() is None

    # Second delete: already gone -> 404.
    assert (await authenticated_async_client.delete(f"{TOKENS_URL}/tok-del")).status_code == 404


@pytest.mark.anyio
async def test_device_token_foreign_delete_404(
    authenticated_async_client: AsyncClient, db: AsyncSession
) -> None:
    other = await _make_user(db, "foreign@t.dev")
    db.add(GameDeviceToken(user_id=other.id, platform="expo", token="tok-foreign"))
    await db.commit()

    response = await authenticated_async_client.delete(f"{TOKENS_URL}/tok-foreign")
    assert response.status_code == 404
    assert (
        await db.execute(select(GameDeviceToken).where(GameDeviceToken.token == "tok-foreign"))
    ).scalar_one_or_none() is not None


# --- Read-all endpoint --------------------------------------------------------


@pytest.mark.anyio
async def test_read_all_marks_only_own_notifications(
    authenticated_async_client: AsyncClient, confirmed_user: dict, db: AsyncSession
) -> None:
    other = await _make_user(db, "spectator@t.dev")
    mine = Notification(
        user_id=confirmed_user["id"], type=NotificationType.SYSTEM, title="a", message="m"
    )
    theirs = Notification(user_id=other.id, type=NotificationType.SYSTEM, title="b", message="m")
    db.add_all([mine, theirs])
    await db.commit()

    response = await authenticated_async_client.post(READ_ALL_URL)
    assert response.status_code == 204

    await db.refresh(mine)
    await db.refresh(theirs)
    assert mine.is_read is True
    assert theirs.is_read is False


# --- Write-path race recovery -------------------------------------------------


def _flaky_flush_after(db: AsyncSession, plant_winner):
    """A db.flush side-effect: on the first call commit `plant_winner` on its
    OWN session (the racing writer), then raise the unique-key IntegrityError
    our losing insert would see. Later flushes run for real."""
    real_flush = db.flush
    attempts = 0

    async def flaky_flush(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            async with TestSessionLocal() as other_db:
                other_db.add(plant_winner())
                await other_db.commit()
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        await real_flush(*args, **kwargs)

    return flaky_flush


@pytest.mark.anyio
async def test_save_notification_pref_insert_race_recovers(db: AsyncSession, mocker) -> None:
    """A concurrent first-PUT hits the user_id uq — rollback + reselect the
    winner's row instead of surfacing an IntegrityError."""
    user = await _make_user(db)
    await db.commit()  # the racing writer's session needs the user row
    user_id = user.id  # capture pre-call — the recovery rollback expires `user`
    mocker.patch.object(
        db,
        "flush",
        side_effect=_flaky_flush_after(
            db, lambda: GameNotificationPref(user_id=user_id, prefs={}, quiet_hours={})
        ),
    )

    pref = await game_crud.save_notification_pref(
        db, user_id, prefs={"low_hp": {"push": False}}, quiet_hours={"start": "21:00"}
    )

    assert pref.prefs == {"low_hp": {"push": False}}
    assert pref.quiet_hours == {"start": "21:00"}


@pytest.mark.anyio
async def test_upsert_device_token_insert_race_recovers(db: AsyncSession, mocker) -> None:
    """Same unique-key race on first register — the winner's row comes back
    reassigned to the caller, no 500."""
    user = await _make_user(db)
    other = await _make_user(db, "tokracer@t.dev")
    await db.commit()
    # Capture pre-call — the recovery rollback expires both user objects.
    user_id, other_id = user.id, other.id
    mocker.patch.object(
        db,
        "flush",
        side_effect=_flaky_flush_after(
            db, lambda: GameDeviceToken(user_id=other_id, platform="expo", token="tok-race")
        ),
    )

    row = await game_crud.upsert_device_token(db, user_id, "expo", "tok-race")

    assert row.user_id == user_id
