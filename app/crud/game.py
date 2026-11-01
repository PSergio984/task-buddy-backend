"""CRUD operations for the game profile, event ledger, and config."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import (
    DiaryEntry,
    FocusPhase,
    FocusSession,
    GameConfig,
    GameEvent,
    GameProfile,
    SessionNote,
)

_RETENTION_DAYS = {"90d": 90, "1y": 365}


def retention_cutoff(retention: str | None, today: date) -> date | None:
    """Earliest visible day for a retention pref; None = 'forever' (no horizon)."""
    days = _RETENTION_DAYS.get(retention or "forever")
    return today - timedelta(days=days) if days else None


def _utc(ts: datetime) -> datetime:
    # Stored timestamps are UTC-aware; a naive value is read as UTC (the same
    # assumption the ingest schema makes for client_ts).
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
        query = query.with_for_update()
    result = await db.execute(query)
    profile = result.scalar_one_or_none()
    if profile is not None:
        return profile
    profile = GameProfile(user_id=user_id)
    db.add(profile)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        result = await db.execute(query)
        profile = result.scalar_one()
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
    db: AsyncSession, user_id: int, since: int | None, limit: int
) -> list[GameEvent]:
    """Ledger catchup feed: events after the last-seen event id, oldest first.

    The cursor is the event id, not server_ts: clock granularity ties could
    permanently hide same-timestamp rows under a timestamp cursor.
    """
    query = select(GameEvent).where(GameEvent.user_id == user_id)
    if since is not None:
        query = query.where(GameEvent.id > since)
    result = await db.execute(query.order_by(GameEvent.id).limit(limit))
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
    limit: int,
) -> list[DiaryEntry]:
    """Newest-first entries; `entry_date` pins one day, `cutoff` is retention."""
    query = select(DiaryEntry).where(DiaryEntry.user_id == user_id)
    if entry_date is not None:
        query = query.where(DiaryEntry.entry_date == entry_date)
    if cutoff is not None:
        query = query.where(DiaryEntry.entry_date >= cutoff)
    result = await db.execute(
        query.order_by(DiaryEntry.entry_date.desc(), DiaryEntry.id.desc()).limit(limit)
    )
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
    instant: on SQLite an aware timestamp stored with a non-UTC offset sorts
    lexically, not chronologically, so a tight filter would mis-bucket it.
    Postgres (timestamptz) is unaffected either way.
    """
    result = await db.execute(
        select(FocusSession).where(
            FocusSession.user_id == user_id,
            FocusSession.started_at >= start - timedelta(days=1),
            FocusSession.started_at < end + timedelta(days=1),
        )
    )
    sessions = [s for s in result.scalars() if start <= _utc(s.started_at) < end]
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
    events = [e for e in result.scalars() if start <= _utc(e.client_ts) < end]
    events.sort(key=lambda e: (e.client_ts, e.id))
    return events
