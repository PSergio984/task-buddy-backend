"""Game notification dispatch: per-type x channel matrix + quiet hours (issue #68).

One entry point — dispatch_notification — reads the user's GameNotificationPref
row (defaults when absent), applies the kind's channel matrix, ALWAYS writes
the in-app Notification row when its channel is on (quiet hours gate push +
email only — the row makes no noise, nothing is lost), then calls the existing
webpush/Brevo senders.

Every per-user "local" axis (reminder times, quiet window, streak-risk day)
comes from the prefs quiet_hours timezone — the documented local answer until
issue #63 lands a real user timezone field. Users without a prefs row evaluate
in UTC.

Trigger hooks live beside dispatch: notify_score_outcome (hp/death/level-up),
notify_phase_end (quiet-exempt, freshness-gated), and run_reminder_tick —
the 60s sweep for habit/daily reminder times plus the once-a-day streak-risk
warning. All hooks swallow their own failures: a notification error must never
break scoring or the sweep's dedupe claim.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import tasks
from app.crud import game as game_crud
from app.models.game import Daily, GameNotificationPref, Habit
from app.models.notification import Notification, NotificationType
from app.models.user import User

logger = logging.getLogger(__name__)

# Local hour (prefs tz) at which the once-a-day streak-risk warning fires.
STREAK_RISK_HOUR = 20
# LOW_HP fires only on a downward crossing of this fraction of max_hp.
LOW_HP_FRACTION = 0.25
# A phase-end alert only fires when its client_ts is this fresh — offline
# replayed batches and next-day session catch-ups must not burst alerts.
PHASE_END_LIVE_SECONDS = 120

# The channels the matrix gates. quiet hours suppress push + email only;
# in_app is the feed row and is written whenever its channel is on.
CHANNELS = ("in_app", "push", "email")

# The kinds the prefs matrix covers; the task-reminder types predate it.
GAME_KINDS = (
    NotificationType.HABIT_REMINDER,
    NotificationType.DAILY_REMINDER,
    NotificationType.STREAK_RISK,
    NotificationType.LOW_HP,
    NotificationType.DAILY_MISSED,
    NotificationType.DEATH,
    NotificationType.PHASE_END,
    NotificationType.LEVEL_UP,
    NotificationType.ACHIEVEMENT,
    NotificationType.RECORD,
)

# Prefs keys are the lowercase enum values (matches the model docstring).
KIND_KEYS = frozenset(k.value.lower() for k in GAME_KINDS)

DEFAULT_CHANNELS: dict[str, bool] = {"in_app": True, "push": True, "email": False}
DEFAULT_QUIET: dict[str, str] = {"start": "22:00", "end": "08:00", "timezone": "UTC"}


def kind_key(kind: NotificationType) -> str:
    """The prefs-matrix key for a kind: its lowercase enum value."""
    return kind.value.lower()


def _parse_hhmm(value: Any) -> int | None:
    """'HH:MM' -> minutes since midnight; None when malformed/stored-garbage."""
    if not isinstance(value, str):
        return None
    try:
        hour_s, minute_s = value.split(":")
        hour, minute = int(hour_s), int(minute_s)
    except (AttributeError, ValueError):
        return None
    return hour * 60 + minute if 0 <= hour <= 23 and 0 <= minute <= 59 else None


def pref_tz(quiet_hours: Any) -> timezone | ZoneInfo:
    """The tz a prefs blob carries; UTC on absent/garbage values."""
    name = quiet_hours.get("timezone") if isinstance(quiet_hours, dict) else None
    try:
        return ZoneInfo(str(name or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def in_quiet_window(quiet_hours: Any, now: datetime) -> bool:
    """Whether `now`'s local wall time sits inside the quiet window."""
    blob = {**DEFAULT_QUIET, **(quiet_hours if isinstance(quiet_hours, dict) else {})}
    start = _parse_hhmm(blob["start"])
    end = _parse_hhmm(blob["end"])
    if start is None or end is None or start == end:
        return False  # malformed or degenerate (start == end) window gates nothing
    local = game_crud.utc_aware(now).astimezone(pref_tz(blob))
    minute = local.hour * 60 + local.minute
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def _matrix_for(stored: Any, kind: NotificationType) -> dict[str, bool]:
    """The kind's effective channel flags: stored overrides merged on defaults.

    A missing/garbage entry collapses to defaults — the matrix is a filter,
    not a value the user proved they want.
    """
    override = stored.get(kind_key(kind)) if isinstance(stored, dict) else None
    if not isinstance(override, dict):
        override = {}
    return {**DEFAULT_CHANNELS, **override}


async def _already_notified(
    db: AsyncSession, user_id: int, kind: NotificationType, meta: dict
) -> bool:
    """Dedup probe: a notification with these exact meta keys already exists.

    Survives the 60s reminder tick — ints compare via as_integer, strings via
    as_string so SQLite's type-preserving JSON_EXTRACT and Postgres ->> agree.
    """
    conds = [
        Notification.user_id == user_id,
        Notification.type == kind,
        *(
            (
                Notification.meta[k].as_integer() == v
                if isinstance(v, int) and not isinstance(v, bool)
                else Notification.meta[k].as_string() == str(v)
            )
            for k, v in meta.items()
        ),
    ]
    return bool((await db.execute(select(exists().where(*conds)))).scalar())


async def dispatch_notification(
    db: AsyncSession,
    user_id: int,
    kind: NotificationType,
    title: str,
    message: str,
    *,
    action_url: str | None = None,
    meta: dict | None = None,
    exempt_quiet: bool = False,
    now: datetime | None = None,
) -> None:
    """Write the feed row and run the enabled senders under the user's prefs.

    The prefs row is read-only here — a get-or-create's race-path rollback
    would wipe a caller's pending scoring work (the same hazard
    get_or_create_profile documents); PUT /game/notification-prefs owns the
    row's creation. Senders are already non-raising (webpush per-sub errors
    and the email chain are logged inside tasks.py).
    """
    now = game_crud.utc_aware(now or datetime.now(timezone.utc))
    pref = await game_crud.get_notification_pref(db, user_id)
    channels = _matrix_for(pref.prefs if pref else None, kind)
    if channels["in_app"]:
        db.add(
            Notification(
                user_id=user_id,
                type=kind,
                title=title,
                message=message,
                action_url=action_url,
                meta=meta,
            )
        )
    if not exempt_quiet and in_quiet_window(pref.quiet_hours if pref else None, now):
        return
    if channels["push"]:
        await tasks._send_push_notification_async(user_id, title, message, action_url)
    if channels["email"]:
        email = (
            await db.execute(select(User.email).where(User.id == user_id))
        ).scalar_one_or_none()
        if email:
            await tasks._send_confirmation_email_async(
                email, title, message, suppress_exceptions=True
            )


async def notify_score_outcome(
    db: AsyncSession,
    user_id: int,
    profile,
    hp_before: float,
    outcome: dict,
    *,
    now: datetime | None = None,
) -> None:
    """DEATH/LOW_HP/LEVEL_UP for one engine outcome. Never raises — a
    notification failure must not break scoring or replay semantics."""
    try:
        if outcome.get("died"):
            # Death outranks LOW_HP — the cascade already reports the hit.
            await dispatch_notification(
                db,
                user_id,
                NotificationType.DEATH,
                "You died!",
                f"HP hit zero — the revive cost a level (now {profile.level}).",
                now=now,
            )
        elif hp_before >= LOW_HP_FRACTION * profile.max_hp > profile.hp and hp_before > profile.hp:
            await dispatch_notification(
                db,
                user_id,
                NotificationType.LOW_HP,
                "HP is low",
                f"Down to {profile.hp:.0f}/{profile.max_hp:.0f} HP — one more hit could kill.",
                now=now,
            )
        if int(outcome.get("levels_gained") or 0) > 0:
            await dispatch_notification(
                db,
                user_id,
                NotificationType.LEVEL_UP,
                "Level up!",
                f"You reached level {profile.level}.",
                action_url="/game",
                now=now,
            )
    except Exception:
        logger.exception("score-outcome notification failed: user=%s", user_id)


async def notify_phase_end(
    db: AsyncSession,
    user_id: int,
    client_ts: datetime,
    minutes: Any = None,
    *,
    now: datetime | None = None,
) -> None:
    """PHASE_END for a live focus-phase completion. Quiet-exempt (timer alerts
    are the spec's exemption) but freshness-gated: a completion older than
    PHASE_END_LIVE_SECONDS is an offline replay/catch-up and stays silent."""
    now = game_crud.utc_aware(now or datetime.now(timezone.utc))
    if abs((now - game_crud.utc_aware(client_ts)).total_seconds()) > PHASE_END_LIVE_SECONDS:
        return
    try:
        body = (
            f"{minutes} minutes focused." if isinstance(minutes, int) else "Focus phase complete."
        )
        await dispatch_notification(
            db,
            user_id,
            NotificationType.PHASE_END,
            "Focus phase complete",
            body,
            action_url="/sessions",
            exempt_quiet=True,
            now=now,
        )
    except Exception:
        logger.exception("phase-end notification failed: user=%s", user_id)


async def _reminder(
    db: AsyncSession,
    user_id: int,
    kind: NotificationType,
    entity_key: str,
    entity_id: int,
    title: str,
    hhmm: str,
    day: date,
    now: datetime,
) -> bool:
    """Dedup + dispatch one reminder; True when it fired."""
    meta = {entity_key: entity_id, "day": day.isoformat(), "time": hhmm}
    if await _already_notified(db, user_id, kind, meta):
        return False
    try:
        await dispatch_notification(
            db,
            user_id,
            kind,
            f"{'Habit' if kind is NotificationType.HABIT_REMINDER else 'Daily'} reminder",
            title,
            action_url="/habits" if kind is NotificationType.HABIT_REMINDER else "/dailies",
            meta=meta,
            now=now,
        )
        return True
    except Exception:
        logger.exception("reminder dispatch failed: user=%s kind=%s", user_id, kind)
        return False


async def _streak_risk(
    db: AsyncSession,
    user_id: int,
    due_today: list[Daily],
    user_dailies: list[Daily],
    day: date,
    now: datetime,
) -> bool:
    """The once-per-local-day 'streak at risk' warning; True when it fired."""
    checks = await game_crud.list_daily_checks(db, [d.id for d in user_dailies], day, day)
    done_ids = {c.daily_id for c in checks if c.daily_item_id is None and c.done}
    unchecked = [d for d in due_today if d.id not in done_ids]
    if not unchecked or await _already_notified(
        db, user_id, NotificationType.STREAK_RISK, {"day": day.isoformat()}
    ):
        return False
    names = ", ".join(d.title for d in unchecked[:5])
    try:
        await dispatch_notification(
            db,
            user_id,
            NotificationType.STREAK_RISK,
            "Dailies still unchecked",
            f"{len(unchecked)} due today — check before day end: {names}.",
            action_url="/dailies",
            meta={"day": day.isoformat()},
            now=now,
        )
        return True
    except Exception:
        logger.exception("streak-risk dispatch failed: user=%s", user_id)
        return False


async def _tick_user(
    db: AsyncSession,
    user_id: int,
    tz,
    habits: list[Habit],
    user_dailies: list[Daily],
    now: datetime,
) -> int:
    """Fire one user's due reminders + streak-risk for this tick's local time."""
    # daily_service is imported lazily — scoring modules import this module
    # for their hooks, and daily_service is one of them (same lazy-import
    # rule achievements.py documents for the cycle).
    from app.game import daily_service

    local = now.astimezone(tz)
    hhmm = local.strftime("%H:%M")
    day = local.date()
    sent = 0
    for habit in habits:
        if hhmm in habit.reminder_times and await _reminder(
            db,
            user_id,
            NotificationType.HABIT_REMINDER,
            "habit_id",
            habit.id,
            f"Time to work on '{habit.title}'.",
            hhmm,
            day,
            now,
        ):
            sent += 1
    due_today: list[Daily] = []
    for daily in user_dailies:
        rec = daily_service.parse_recurrence(daily.recurrence)
        if rec is None or not daily_service.is_schedulable(
            rec, day, daily_service.daily_anchor(daily)
        ):
            continue
        due_today.append(daily)
        if (
            daily.reminder_times
            and hhmm in daily.reminder_times
            and await _reminder(
                db,
                user_id,
                NotificationType.DAILY_REMINDER,
                "daily_id",
                daily.id,
                f"'{daily.title}' is scheduled today.",
                hhmm,
                day,
                now,
            )
        ):
            sent += 1
    if local.hour == STREAK_RISK_HOUR and due_today:
        sent += await _streak_risk(db, user_id, due_today, user_dailies, day, now)
    return sent


async def run_reminder_tick(
    now: datetime | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """One game-reminder pass over every user with habits/dailies.

    Fires when the user's local HH:MM (prefs tz, UTC fallback) matches an
    entity's reminder_times — habit reminders always, daily reminders only
    when the recurrence schedules today. At local hour STREAK_RISK_HOUR a
    consolidated warning lists scheduled-but-unchecked dailies. Dedup anchors
    on (user, kind, entity+day+time) meta so overlapping ticks can't
    re-deliver. Returns notifications dispatched; `now`/`session_factory`
    are injectable for tests (same contract as run_daily_miss_sweep).
    """
    if session_factory is None:
        from app.database import AsyncSessionLocal

        session_factory = AsyncSessionLocal
    now = game_crud.utc_aware(now or datetime.now(timezone.utc))
    async with session_factory() as db:
        pref_rows = (await db.execute(select(GameNotificationPref))).scalars().all()
        tz_by_user = {p.user_id: pref_tz(p.quiet_hours) for p in pref_rows}
        habits_by_user: dict[int, list[Habit]] = {}
        for habit in (await db.execute(select(Habit))).scalars().all():
            if habit.reminder_times:
                habits_by_user.setdefault(habit.user_id, []).append(habit)
        # Streak-risk needs every active daily per user — reminder gating on
        # reminder_times is applied per row below.
        dailies_by_user: dict[int, list[Daily]] = {}
        for daily in (
            (await db.execute(select(Daily).where(Daily.active.is_(True)))).scalars().all()
        ):
            dailies_by_user.setdefault(daily.user_id, []).append(daily)
        sent = 0
        for user_id in set(habits_by_user) | set(dailies_by_user):
            sent += await _tick_user(
                db,
                user_id,
                tz_by_user.get(user_id, timezone.utc),
                habits_by_user.get(user_id, []),
                dailies_by_user.get(user_id, []),
                now,
            )
        await db.commit()
    return sent
