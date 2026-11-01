"""CRUD operations for the game profile, event ledger, and config."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import GameConfig, GameEvent, GameProfile


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
