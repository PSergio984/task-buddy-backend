"""API endpoints for the profile Stats/Activity tab (#66): the contribution
grid's per-day scores and the stat set — read-only aggregations over the
event ledger and focus phases."""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_GAME_READ
from app.crud import game_tracking as tracking_crud
from app.dependencies import get_db
from app.game import tracking
from app.limiter import limiter
from app.models.user import User
from app.schemas.game_tracking import (
    ActivityDay,
    ActivityGridResponse,
    ActivityStatsResponse,
)
from app.security import get_confirmed_user

router = APIRouter(
    prefix="/game/activity",
    tags=["game"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
    },
)


def _resolve_range(start: Optional[date], end: Optional[date]) -> tuple[date, date]:
    """Defaults + bounds for the [start, end] UTC window (inclusive).

    `end` clamps to today — future tail days can never score, so leaving
    them in the window would zero the current streak and dilute the
    daily-hours average. `end` is bounds-checked because the defaulting
    subtraction and the exclusive-upper-bound addition below both overflow
    on extreme dates (mirrors get_timeline's guard).
    """
    today = datetime.now(timezone.utc).date()
    if end is not None and not (
        date.min + timedelta(days=tracking.DEFAULT_WINDOW_DAYS)
        <= end
        <= date.max - timedelta(days=1)
    ):
        raise HTTPException(status_code=400, detail="end date out of supported range")
    resolved_end = min(end, today) if end is not None else today
    resolved_start = start or (resolved_end - timedelta(days=tracking.DEFAULT_WINDOW_DAYS - 1))
    if resolved_start > resolved_end:
        raise HTTPException(status_code=400, detail="start must be on or before end")
    if (resolved_end - resolved_start).days >= tracking.MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"date range exceeds {tracking.MAX_RANGE_DAYS} days",
        )
    return resolved_start, resolved_end


async def _day_rows(
    db: AsyncSession, user_id: int, start: date, end: date
) -> tuple[list[dict], list[float]]:
    """Aggregate the window into filled per-day rows (empty days included)."""
    rates = await tracking.load_rates(db)
    # UTC instants bounding the inclusive day window.
    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_dt = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)
    counts = await tracking_crud.get_event_counts_by_day(db, user_id, start_dt, end_dt)
    phase_minutes = await tracking_crud.get_focus_minutes_by_day(db, user_id, start_dt, end_dt)
    client_minutes = await tracking_crud.get_client_focus_minutes_by_day(
        db, user_id, start_dt, end_dt
    )
    minutes = {
        day: phase_minutes.get(day, 0.0) + client_minutes.get(day, 0.0)
        for day in phase_minutes.keys() | client_minutes.keys()
    }
    return tracking.build_days(start, end, minutes, counts, rates), list(rates.tier_thresholds)


@router.get("", response_model=ActivityGridResponse)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_activity_grid(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: Annotated[Optional[date], Query()] = None,
    end: Annotated[Optional[date], Query()] = None,
) -> ActivityGridResponse:
    """The contribution grid: per-day score, focus minutes, event counts and
    intensity tier — one row per UTC day in the window (default last 365)."""
    start, end = _resolve_range(start, end)
    days, thresholds = await _day_rows(db, current_user.id, start, end)
    return ActivityGridResponse(
        start=start,
        end=end,
        days=[ActivityDay(**row) for row in days],
        tier_thresholds=thresholds,
        server_time=datetime.now(timezone.utc),
    )


@router.get("/stats", response_model=ActivityStatsResponse)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_activity_stats(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: Annotated[Optional[date], Query()] = None,
    end: Annotated[Optional[date], Query()] = None,
) -> ActivityStatsResponse:
    """The profile stat set over the same window: hours, streaks, best day,
    weekly total. Streaks are bounded by the window; speedrun PBs are
    all-time and fetched separately from the day rows."""
    start, end = _resolve_range(start, end)
    days, _ = await _day_rows(db, current_user.id, start, end)
    pbs = await tracking_crud.get_speedrun_pbs(db, current_user.id)
    stats = tracking.summarize(days, datetime.now(timezone.utc).date(), speedrun_pbs=pbs)
    return ActivityStatsResponse(
        start=start, end=end, server_time=datetime.now(timezone.utc), **stats
    )
