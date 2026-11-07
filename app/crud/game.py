"""CRUD operations for the game profile, event ledger, and config."""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.game.session_engine import MIN_RECORD_SECONDS
from app.models.game import (
    Daily,
    DailyCheck,
    DailyItem,
    DailyMiss,
    DiaryEntry,
    FocusPhase,
    FocusSession,
    GameConfig,
    GameDeviceToken,
    GameEvent,
    GameNotificationPref,
    GameProfile,
    GearItem,
    Habit,
    SessionNote,
    UserGear,
)

logger = logging.getLogger(__name__)

_RETENTION_DAYS = {"90d": 90, "1y": 365}


def retention_cutoff(retention: str | None, today: date) -> date | None:
    """Earliest visible day for a retention pref; None = 'forever' (no horizon)."""
    days = _RETENTION_DAYS.get(retention or "forever")
    return today - timedelta(days=days) if days else None


def utc_aware(ts: datetime) -> datetime:
    # SQLite reads DateTime(timezone=True) back tz-naive (the offset is not
    # stored); a naive value is labeled UTC — the same assumption the ingest
    # schema makes for client_ts.
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


async def get_or_create_profile(
    db: AsyncSession, user_id: int, *, for_update: bool = False
) -> GameProfile:
    """Fetch the user's game profile, creating the default one on first use.

    for_update takes SELECT FOR UPDATE — ingest locks the profile row so two
    concurrent batches can't read-modify-write over each other. The lock also
    serializes per-user ingestion, which makes the dedupe SELECT that follows
    race-free. On first use, a losing create race hits the user_id unique
    constraint; recover by re-selecting the committed row. Only safe to call
    at the start of a transaction: the race path rolls back pending work.
    """
    query = select(GameProfile).where(GameProfile.user_id == user_id)
    if for_update:
        # Postgres-only clause (dropped silently on SQLite — the test
        # backend serializes writes at the file level anyway).
        # populate_existing is load-bearing: expire_on_commit=False means a
        # profile already in the identity map (e.g. an earlier read this
        # request) would come back stale without the forced fresh read.
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
    profile = result.scalar_one_or_none()
    if profile is not None:
        # Stamp the read/lock instant: server_time-ordered merges must rank
        # a snapshot by when its data was read, not when the response built —
        # a concurrent write can commit during this request's later awaits.
        profile._loaded_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        return profile
    profile = GameProfile(user_id=user_id)
    db.add(profile)
    try:
        await db.flush()
    except IntegrityError:
        # A create-race rollback releases any locks the caller took before
        # this function (ingest_events locks session rows first for order
        # safety) — narrow first-write window; the locks are re-acquired
        # implicitly on next access only inside a serializable txn.
        await db.rollback()
        result = await db.execute(query)
        profile = result.scalar_one()
    profile._loaded_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
    return profile


async def update_avatar_config(db: AsyncSession, user_id: int, config: dict) -> GameProfile:
    """Replace the user's avatar_config blob; creates the profile on first use."""
    profile = await get_or_create_profile(db, user_id)
    profile.avatar_config = config
    await db.flush()
    return profile


async def existing_event_ids(
    db: AsyncSession, user_id: int, client_event_ids: list[str]
) -> set[str]:
    """Return the subset of client_event_ids already recorded for the user."""
    if not client_event_ids:
        return set()
    result = await db.execute(
        select(GameEvent.client_event_id).where(
            GameEvent.user_id == user_id,
            GameEvent.client_event_id.in_(client_event_ids),
        )
    )
    return set(result.scalars().all())


async def get_events_since(
    db: AsyncSession, user_id: int, since: int | None, limit: int, *, desc: bool = False
) -> list[GameEvent]:
    """Ledger catchup feed: events after the last-seen event id, oldest first.

    The cursor is the event id, not server_ts: clock granularity ties could
    permanently hide same-timestamp rows under a timestamp cursor. `desc`
    flips the direction — newest first — and `since` then means "older than
    this id", so history can page backwards instead of replaying the whole
    ledger from 0.
    """
    query = select(GameEvent).where(GameEvent.user_id == user_id)
    if since is not None:
        query = query.where(GameEvent.id < since if desc else GameEvent.id > since)
    ordering = GameEvent.id.desc() if desc else GameEvent.id
    result = await db.execute(query.order_by(ordering).limit(limit))
    return list(result.scalars().all())


async def get_config_map(db: AsyncSession) -> dict[str, dict]:
    """All game_config rows keyed by their config key."""
    result = await db.execute(select(GameConfig))
    return {row.key: row.value for row in result.scalars().all()}


async def get_retention(db: AsyncSession, user_id: int) -> str:
    """The user's retention preference; a missing profile reads as 'forever'.

    Read paths don't autocreate the profile — a diary GET shouldn't write a
    profile row just to learn the default.
    """
    result = await db.execute(select(GameProfile.retention).where(GameProfile.user_id == user_id))
    return result.scalar_one_or_none() or "forever"


async def find_standup(db: AsyncSession, user_id: int, entry_date: date) -> DiaryEntry | None:
    result = await db.execute(
        select(DiaryEntry).where(
            DiaryEntry.user_id == user_id,
            DiaryEntry.entry_date == entry_date,
            DiaryEntry.kind == "standup",
        )
    )
    return result.scalar_one_or_none()


async def get_diary_entry(db: AsyncSession, user_id: int, entry_id: int) -> DiaryEntry | None:
    result = await db.execute(
        select(DiaryEntry).where(DiaryEntry.id == entry_id, DiaryEntry.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_diary_entries(
    db: AsyncSession,
    user_id: int,
    entry_date: date | None,
    cutoff: date | None,
    limit: int | None = None,
    offset: int = 0,
) -> list[DiaryEntry]:
    """Newest-first entries; `entry_date` pins one day, `cutoff` is retention."""
    query = select(DiaryEntry).where(DiaryEntry.user_id == user_id)
    if entry_date is not None:
        query = query.where(DiaryEntry.entry_date == entry_date)
    if cutoff is not None:
        query = query.where(DiaryEntry.entry_date >= cutoff)
    query = query.order_by(DiaryEntry.entry_date.desc(), DiaryEntry.id.desc())
    if limit is not None:
        query = query.limit(limit)
    if offset:
        query = query.offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_focus_session(db: AsyncSession, session_id: int, user_id: int) -> FocusSession | None:
    result = await db.execute(
        select(FocusSession).where(FocusSession.id == session_id, FocusSession.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def find_session_note(db: AsyncSession, session_id: int) -> SessionNote | None:
    result = await db.execute(select(SessionNote).where(SessionNote.session_id == session_id))
    return result.scalar_one_or_none()


async def get_sessions_started_between(
    db: AsyncSession, user_id: int, start: datetime, end: datetime
) -> list[FocusSession]:
    """Sessions whose started_at lands inside [start, end) on the UTC axis.

    The SQL window is widened a day each side and re-filtered on the UTC
    instant: SQLite stores timestamps without the offset, so lexical bounds
    alone can't be trusted once a client writes a non-UTC wall time. Postgres
    (timestamptz) is unaffected either way.
    """
    result = await db.execute(
        select(FocusSession).where(
            FocusSession.user_id == user_id,
            FocusSession.started_at >= start - timedelta(days=1),
            FocusSession.started_at < end + timedelta(days=1),
        )
    )
    sessions = [s for s in result.scalars() if start <= utc_aware(s.started_at) < end]
    sessions.sort(key=lambda s: (s.started_at, s.id))
    return sessions


async def get_phases_for_sessions(db: AsyncSession, session_ids: list[int]) -> list[FocusPhase]:
    if not session_ids:
        return []
    result = await db.execute(
        select(FocusPhase)
        .where(FocusPhase.session_id.in_(session_ids))
        .order_by(FocusPhase.session_id, FocusPhase.seq)
    )
    return list(result.scalars().all())


async def get_events_between(
    db: AsyncSession, user_id: int, start: datetime, end: datetime
) -> list[GameEvent]:
    """Ledger rows whose client_ts lands inside [start, end) — the marker axis.

    Same widened-window + UTC re-filter as get_sessions_started_between:
    client_ts is client-supplied and may carry a non-UTC offset.
    """
    result = await db.execute(
        select(GameEvent).where(
            GameEvent.user_id == user_id,
            GameEvent.client_ts >= start - timedelta(days=1),
            GameEvent.client_ts < end + timedelta(days=1),
        )
    )
    events = [e for e in result.scalars() if start <= utc_aware(e.client_ts) < end]
    events.sort(key=lambda e: (e.client_ts, e.id))
    return events


async def get_session(
    db: AsyncSession, session_id: int, user_id: int, *, for_update: bool = False
) -> FocusSession | None:
    """A session by id, scoped to its owner."""
    query = select(FocusSession).where(
        FocusSession.id == session_id, FocusSession.user_id == user_id
    )
    if for_update:
        # populate_existing is load-bearing (same as get_or_create_profile):
        # a session already in the identity map would shadow the locked row.
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def lock_sessions(db: AsyncSession, user_id: int, session_ids: list[int]) -> None:
    """SELECT FOR UPDATE the user's sessions, in id order.

    Ingest takes these locks BEFORE the profile FOR UPDATE so the batch's
    session->profile order matches the verb path's (_locked_session then
    _evaluate's profile lock) — the opposite direction is the Postgres
    cross-deadlock (40P01). Ordering by id keeps two concurrent batches'
    acquisition order identical; unresolvable ids simply match no row.
    """
    if not session_ids:
        return
    await db.execute(
        select(FocusSession)
        .where(FocusSession.user_id == user_id, FocusSession.id.in_(session_ids))
        .order_by(FocusSession.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def get_active_session(
    db: AsyncSession, user_id: int, *, for_update: bool = False
) -> FocusSession | None:
    """The user's single in-flight session, if any. The partial unique index
    uq_focus_sessions_one_active guarantees at most one 'active' row."""
    query = select(FocusSession).where(
        FocusSession.user_id == user_id, FocusSession.status == "active"
    )
    if for_update:
        # get_active_view probes unlocked first — without populate_existing
        # the probe's identity-map copy would shadow the locked row here.
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_phases(db: AsyncSession, session_id: int) -> list[FocusPhase]:
    """A session's phases in sequence order."""
    result = await db.execute(
        select(FocusPhase).where(FocusPhase.session_id == session_id).order_by(FocusPhase.seq)
    )
    return list(result.scalars().all())


async def get_speedrun_record(
    db: AsyncSession, user_id: int, activity_label: str | None
) -> int | None:
    """The standing beat-your-best record for an activity label: the fastest
    completed beat_best speedrun phase (None when the label has never run).

    The record is derived, not stored: MIN(actual_seconds) over completed
    speedrun phases of the user's beat_best sessions for the label — only
    runs at/above MIN_RECORD_SECONDS are board-eligible (the same floor
    done() applies, so a sub-minute finish never reaches here as a record).
    The speedrun->>'type' extraction works on both dialects (JSON_EXTRACT on
    SQLite, ->> on Postgres — same precedent as payload._outcome reads).
    """
    result = await db.execute(
        select(func.min(FocusPhase.actual_seconds))
        .join(FocusSession, FocusPhase.session_id == FocusSession.id)
        .where(
            FocusSession.user_id == user_id,
            FocusSession.mode == "speedrun",
            FocusSession.activity_label == activity_label,
            FocusSession.speedrun["type"].as_string() == "beat_best",
            FocusPhase.kind == "speedrun",
            FocusPhase.status == "completed",
            FocusPhase.actual_seconds >= MIN_RECORD_SECONDS,
        )
    )
    return result.scalar_one()


async def list_recent_ended_phone_blobs(
    db: AsyncSession,
    user_id: int,
    exclude_id: int,
    limit: int,
    *,
    ended_before: datetime | None = None,
) -> list[dict | None]:
    """phone_down blobs of the user's most recently finished sessions, newest first.

    The verified-streak derivation (#70) needs every finished session in the
    window — not just enabled ones — so a non-phone-down session correctly
    breaks the run. Abandoned sessions are included: their blob still carries
    the violation/span evidence, and an abandon is never a clean run — they
    report as None to the walk (the blob itself stays on the session row for
    history). `ended_before` bounds the window to sessions finished before
    the scored session's own end (or the scoring instant while it's live),
    so a catch-up scoring can't credit younger completions toward its streak.
    Adjudication lives in app.game.phone_down.
    """
    query = select(FocusSession.phone_down, FocusSession.status).where(
        FocusSession.user_id == user_id,
        FocusSession.id != exclude_id,
        FocusSession.status.in_(("ended", "abandoned")),
        # A corrupt finished row can carry NULL ended_at — Postgres sorts
        # NULLS FIRST on DESC, so it would consume a walk slot and break
        # the streak conservatively; just exclude it.
        FocusSession.ended_at.is_not(None),
    )
    if ended_before is not None:
        query = query.where(FocusSession.ended_at <= ended_before)
    result = await db.execute(
        query.order_by(FocusSession.ended_at.desc(), FocusSession.id.desc()).limit(limit)
    )
    return [blob if status == "ended" else None for blob, status in result.tuples().all()]


async def list_phone_down_violation_events(
    db: AsyncSession, user_id: int, session_id: int, started_at: datetime
) -> list[GameEvent]:
    """The user's phone_down_violation ledger rows for one session.

    The server_ts >= started_at bound drops rows received before the
    session existed — impossible for a legit report (the session must
    exist before an event can reference it), and server-stamped so a
    client can't backdate client_ts to make a violation invisible to
    adjudication. The at_ts window check stays caller-side and
    authoritative. Only applied rows carry session_id (the ingest strips
    client extras and writes the resolved id back), so the SQL payload
    filter keeps rejected events out — the payload[...].as_integer()
    extraction reads JSON on both backends (game_tracking's
    payload["minutes"].as_float() precedent).
    """
    result = await db.execute(
        select(GameEvent).where(
            GameEvent.user_id == user_id,
            GameEvent.type == "phone_down_violation",
            GameEvent.server_ts >= started_at,
            GameEvent.payload["session_id"].as_integer() == session_id,
        )
    )
    return list(result.scalars().all())


async def list_recent_phone_down_violations(
    db: AsyncSession, user_id: int, since_server_ts: datetime
) -> list[GameEvent]:
    """The user's applied phone_down_violation rows server-received since
    the repeat-window floor — the penalty path's cross-session scan.

    session_id presence marks an applied row (rejected events never get
    the server-reserved key written back), so it doubles as the
    applied-only filter. The at_ts window check stays caller-side and
    authoritative; server_ts only bounds the scan.
    """
    result = await db.execute(
        select(GameEvent).where(
            GameEvent.user_id == user_id,
            GameEvent.type == "phone_down_violation",
            GameEvent.server_ts >= since_server_ts,
            # as_integer() then IS NOT NULL: a bare index is_not() compiles
            # to JSON_QUOTE(json_extract(...)) on SQLite, and json_quote(NULL)
            # is the 'null' string — never NULL — so rejected rows would
            # leak into the penalty scan there (Postgres ->> is fine).
            GameEvent.payload["session_id"].as_integer().is_not(None),
        )
    )
    return list(result.scalars().all())


async def list_recent_phone_down_penalties(
    db: AsyncSession, user_id: int, since_server_ts: datetime
) -> list[GameEvent]:
    """The user's phone_down_violations damage rows since the same server
    floor — their `charged_ats` payloads carry the durable cross-session
    "already fined" set (the session blob's penalized_violation_ats is
    pruned and session-local). The "server:" eid prefix keeps
    client-authored damage claims out — the prefix is schema-reserved, so
    a client can't forge charged_ats to pre-mark violations as fined."""
    result = await db.execute(
        select(GameEvent).where(
            GameEvent.user_id == user_id,
            GameEvent.type == "damage",
            GameEvent.server_ts >= since_server_ts,
            GameEvent.client_event_id.ilike("server:%"),
            GameEvent.payload["reason"].as_string() == "phone_down_violations",
        )
    )
    return list(result.scalars().all())


async def get_habit(db: AsyncSession, user_id: int, habit_id: int) -> Habit | None:
    """One habit by id, scoped to its owner."""
    result = await db.execute(select(Habit).where(Habit.id == habit_id, Habit.user_id == user_id))
    return result.scalar_one_or_none()


async def list_habits(db: AsyncSession, user_id: int) -> list[Habit]:
    """All of the user's habits in creation order."""
    result = await db.execute(select(Habit).where(Habit.user_id == user_id).order_by(Habit.id))
    return list(result.scalars().all())


async def get_daily(db: AsyncSession, user_id: int, daily_id: int) -> Daily | None:
    """One daily by id, scoped to its owner."""
    result = await db.execute(select(Daily).where(Daily.id == daily_id, Daily.user_id == user_id))
    return result.scalar_one_or_none()


async def list_dailies(db: AsyncSession, user_id: int) -> list[Daily]:
    """All of the user's dailies in creation order."""
    result = await db.execute(select(Daily).where(Daily.user_id == user_id).order_by(Daily.id))
    return list(result.scalars().all())


async def count_dailies(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(select(func.count(Daily.id)).where(Daily.user_id == user_id))
    return int(result.scalar_one())


async def list_active_daily_ids(db: AsyncSession, after_id: int, limit: int) -> list[int]:
    """One id-ordered page of active daily ids for the miss sweep.

    Ids only: the sweep re-reads each row inside its per-daily try (a
    post-rollback identity-map hit would be expired).
    """
    result = await db.execute(
        select(Daily.id)
        .where(Daily.active.is_(True), Daily.id > after_id)
        .order_by(Daily.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_daily_items(db: AsyncSession, daily_ids: list[int]) -> list[DailyItem]:
    """Checklist rows for the given dailies in position order."""
    if not daily_ids:
        return []
    result = await db.execute(
        select(DailyItem)
        .where(DailyItem.daily_id.in_(daily_ids))
        .order_by(DailyItem.daily_id, DailyItem.position, DailyItem.id)
    )
    return list(result.scalars().all())


async def list_daily_checks(
    db: AsyncSession, daily_ids: list[int], start: date, end: date
) -> list[DailyCheck]:
    """Check marks for the given dailies on check_date in [start, end]."""
    if not daily_ids:
        return []
    result = await db.execute(
        select(DailyCheck).where(
            DailyCheck.daily_id.in_(daily_ids),
            DailyCheck.check_date >= start,
            DailyCheck.check_date <= end,
        )
    )
    return list(result.scalars().all())


async def list_daily_misses(db: AsyncSession, daily_id: int, since: date) -> list[DailyMiss]:
    """Miss rows for one daily on/after `since` — sweep + freeze bookkeeping."""
    result = await db.execute(
        select(DailyMiss).where(DailyMiss.daily_id == daily_id, DailyMiss.scheduled_day >= since)
    )
    return list(result.scalars().all())


async def get_daily_miss(db: AsyncSession, daily_id: int, scheduled_day: date) -> DailyMiss | None:
    """The miss row for one (daily, scheduled_day), if the sweep recorded one."""
    result = await db.execute(
        select(DailyMiss).where(
            DailyMiss.daily_id == daily_id, DailyMiss.scheduled_day == scheduled_day
        )
    )
    return result.scalar_one_or_none()


async def list_daily_check_events(
    db: AsyncSession, user_id: int, since: datetime, until: datetime
) -> list[GameEvent]:
    """The user's daily_check ledger rows in [since, until] (client_ts bound).

    Server-side prefilter for paid-share accounting — callers narrow to a
    (daily_id, check_date) pair via payload keys in Python, which keeps the
    query portable across Postgres JSONB and SQLite JSON. The upper bound
    keeps pathological far-future timestamps out of the scan; the caller
    picks `until` so rows that legitimately scored can't fall outside it.
    """
    result = await db.execute(
        select(GameEvent).where(
            GameEvent.user_id == user_id,
            GameEvent.type == "daily_check",
            GameEvent.client_ts >= since,
            GameEvent.client_ts <= until,
        )
    )
    return list(result.scalars().all())


# --- Character sheet: gear + achievements (issue #64) ------------------------


async def list_equipped_gear(db: AsyncSession, user_id: int) -> list[tuple[UserGear, GearItem]]:
    """(user_gear, catalog-item) pairs for everything currently equipped."""
    result = await db.execute(
        select(UserGear, GearItem)
        .join(GearItem, UserGear.gear_item_id == GearItem.id)
        .where(UserGear.user_id == user_id, UserGear.equipped.is_(True))
    )
    return list(result.tuples().all())


async def list_gear_catalog(db: AsyncSession) -> list[GearItem]:
    """Every catalog row, ordered for a stable client display."""
    result = await db.execute(
        select(GearItem).order_by(GearItem.klass, GearItem.slot, GearItem.tier)
    )
    return list(result.scalars().all())


async def get_gear_item(db: AsyncSession, key: str) -> GearItem | None:
    result = await db.execute(select(GearItem).where(GearItem.key == key))
    return result.scalar_one_or_none()


async def find_gear_item(db: AsyncSession, *, slot: str, klass: str, tier: int) -> GearItem | None:
    """Ladder lookup: the piece one tier back in the same slot+class."""
    result = await db.execute(
        select(GearItem).where(
            GearItem.slot == slot, GearItem.klass == klass, GearItem.tier == tier
        )
    )
    return result.scalar_one_or_none()


async def get_user_gear(db: AsyncSession, user_id: int, gear_item_id: int) -> UserGear | None:
    result = await db.execute(
        select(UserGear).where(UserGear.user_id == user_id, UserGear.gear_item_id == gear_item_id)
    )
    return result.scalar_one_or_none()


async def list_user_gear(db: AsyncSession, user_id: int) -> list[UserGear]:
    result = await db.execute(select(UserGear).where(UserGear.user_id == user_id))
    return list(result.scalars().all())


# --- Notification prefs + device tokens (issue #68) -------------------------


async def get_notification_pref(db: AsyncSession, user_id: int) -> GameNotificationPref | None:
    """The user's notification prefs row; None = defaults everywhere."""
    result = await db.execute(
        select(GameNotificationPref).where(GameNotificationPref.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def save_notification_pref(
    db: AsyncSession, user_id: int, prefs: dict, quiet_hours: dict
) -> GameNotificationPref:
    """Create-or-replace the user's prefs row (PUT semantics — whole object).

    A losing first-PUT race hits the user_id unique constraint on flush —
    recover by re-selecting the winner's committed row, the
    get_or_create_profile pattern (the rollback also discards the caller's
    earlier pending work, so this is only safe at transaction start).
    """
    pref = await get_notification_pref(db, user_id)
    if pref is not None:
        pref.prefs = prefs
        pref.quiet_hours = quiet_hours
        await db.flush()
        return pref
    pref = GameNotificationPref(user_id=user_id, prefs=prefs, quiet_hours=quiet_hours)
    db.add(pref)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        pref = (
            await db.execute(
                select(GameNotificationPref).where(GameNotificationPref.user_id == user_id)
            )
        ).scalar_one()  # the race winner's committed row
        pref.prefs = prefs
        pref.quiet_hours = quiet_hours
        await db.flush()
    return pref


async def upsert_device_token(
    db: AsyncSession, user_id: int, platform: str, token: str
) -> GameDeviceToken:
    """Register a device token, reassigning it to the caller when it exists —
    same upsert-on-unique-key pattern as push subscriptions.

    A losing first-register race hits the token unique constraint on
    flush — recover by re-selecting the winner's committed row, the
    get_or_create_profile pattern (the rollback also discards the caller's
    earlier pending work, so this is only safe at transaction start).
    """
    result = await db.execute(select(GameDeviceToken).where(GameDeviceToken.token == token))
    row = result.scalar_one_or_none()
    if row is None:
        row = GameDeviceToken(user_id=user_id, platform=platform, token=token)
        db.add(row)
        try:
            await db.flush()
            return row
        except IntegrityError:
            await db.rollback()
            row = (
                await db.execute(select(GameDeviceToken).where(GameDeviceToken.token == token))
            ).scalar_one()
    if row.user_id != user_id:
        # An ownership hand-off (client-side or race-won) stays audible.
        logger.info("device token reassigned from user=%s to user=%s", row.user_id, user_id)
    row.user_id = user_id
    row.platform = platform
    await db.flush()
    return row


async def delete_device_token(db: AsyncSession, user_id: int, token: str) -> bool:
    """Remove a token owned by the caller; False = not found/not theirs."""
    result: CursorResult = await db.execute(  # type: ignore[assignment]
        delete(GameDeviceToken).where(
            GameDeviceToken.token == token, GameDeviceToken.user_id == user_id
        )
    )
    return result.rowcount > 0
