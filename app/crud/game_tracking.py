"""Read-only per-day aggregations for the activity grid / profile stats.

All day bucketing is UTC — there is no per-user timezone, and the rest of
the game layer (timeline day windows, daily-cap bookkeeping) already treats
UTC as the day axis. Bucketing happens in SQL (GROUP BY the day expression),
not by loading raw rows: the result is bounded by the 366-day window, while
the scanned rows are bounded by (user_id, ts range).

Index assumptions: tbl_game_events is filtered on (user_id, client_ts) —
ix_game_events_user_feed leads with user_id, and the per-user range is small
enough for the residual scan. Focus phases are reached through
tbl_focus_sessions.user_id (indexed) then the session_id index on phases.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.models.game import FocusPhase, FocusSession, GameConfig, GameEvent

# Phase kinds that represent focus time; breaks never do. Completed is the
# only status with real actual_seconds (skipped/abandoned phases didn't run
# their course — mirroring session_engine, which scores completions only).
_FOCUS_KINDS = ("focus", "stopwatch")
_COMPLETED = "completed"


def _day_expr(db: AsyncSession, column: InstrumentedAttribute[Any]) -> ColumnElement[Any]:
    """The UTC calendar date of a stored instant, as a SQL expression.

    Postgres: `column AT TIME ZONE 'UTC'` drops the tz at UTC, then date()
    clips the day — session-TZ independent. SQLite: DateTime columns are
    stored as 'YYYY-MM-DD HH:MM:SS' text, already UTC (the ingest schema
    normalizes offsets, and server writes are aware now()s), so date()
    clips the day directly.
    """
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return func.date(func.timezone("UTC", column))
    return func.date(column)


def _to_date(value) -> date:
    """Normalize a day-expression result: date on Postgres, str on SQLite."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


async def get_activity_config(db: AsyncSession) -> dict:
    """The activity_weights config row's value; absent -> {} (defaults apply)."""
    row = await db.get(GameConfig, "activity_weights")
    return dict(row.value) if row is not None else {}


async def get_event_counts_by_day(
    db: AsyncSession, user_id: int, start: datetime, end: datetime
) -> dict[date, dict[str, int]]:
    """Ledger events per day per type: {day: {type: count}}.

    Bucketed on client_ts — the same marker axis the timeline uses, so a
    backdated client event lands on the day the client claims, and offline
    syncs fill past cells instead of piling onto today.
    """
    day = _day_expr(db, GameEvent.client_ts)
    result = await db.execute(
        select(day, GameEvent.type, func.count())
        .where(
            GameEvent.user_id == user_id,
            GameEvent.client_ts >= start,
            GameEvent.client_ts < end,
        )
        .group_by(day, GameEvent.type)
    )
    counts: dict[date, dict[str, int]] = {}
    for row_day, event_type, n in result.all():
        counts.setdefault(_to_date(row_day), {})[event_type] = n
    return counts


async def get_focus_minutes_by_day(
    db: AsyncSession, user_id: int, start: datetime, end: datetime
) -> dict[date, float]:
    """Server-side focus minutes per day from completed focus/stopwatch phases.

    Bucketed on the phase's ended_at — the completion instant is also what
    the ledger's focus_phase_completed carries, so both sources agree on
    which day a phase belongs to.
    """
    day = _day_expr(db, FocusPhase.ended_at)
    result = await db.execute(
        select(day, func.coalesce(func.sum(FocusPhase.actual_seconds), 0))
        .join(FocusSession, FocusPhase.session_id == FocusSession.id)
        .where(
            FocusSession.user_id == user_id,
            FocusPhase.kind.in_(_FOCUS_KINDS),
            FocusPhase.status == _COMPLETED,
            FocusPhase.ended_at >= start,
            FocusPhase.ended_at < end,
        )
        .group_by(day)
    )
    return {_to_date(row_day): float(seconds or 0) / 60.0 for row_day, seconds in result.all()}


async def get_client_focus_minutes_by_day(
    db: AsyncSession, user_id: int, start: datetime, end: datetime
) -> dict[date, float]:
    """Offline-synced focus minutes: client-authored focus_phase_completed rows.

    Server-authored rows (client_event_id 'server:...') are excluded — their
    minutes are already counted through the FocusPhase rows above, so reading
    both would double-count. Stored payloads carry a validated numeric
    `minutes` (the ingest engine rejects non-numbers before the row lands),
    so the ->> cast is safe.
    """
    day = _day_expr(db, GameEvent.client_ts)
    minutes = GameEvent.payload["minutes"].as_float()
    result = await db.execute(
        select(day, func.coalesce(func.sum(minutes), 0.0))
        .where(
            GameEvent.user_id == user_id,
            GameEvent.type == "focus_phase_completed",
            GameEvent.client_event_id.not_like("server:%"),
            GameEvent.client_ts >= start,
            GameEvent.client_ts < end,
        )
        .group_by(day)
    )
    return {_to_date(row_day): float(m or 0.0) for row_day, m in result.all()}
