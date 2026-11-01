"""API endpoints for the gamified focus layer: profile + event ledger sync."""

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_GAME_EVENTS, RATE_LIMIT_GAME_READ
from app.crud import game as game_crud
from app.dependencies import get_db
from app.game import engine, service
from app.limiter import limiter
from app.models.user import User
from app.schemas.game import (
    GameEventBatch,
    GameEventRead,
    GameEventsFeedResponse,
    GameProfileRead,
    GameSyncResponse,
)
from app.security import get_confirmed_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/game",
    tags=["game"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
    },
)


def _to_profile_read(profile, rates) -> GameProfileRead:
    return GameProfileRead.from_profile(profile, engine.xp_to_next_level(profile.level, rates))


@router.get("/profile", response_model=GameProfileRead)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_profile(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameProfileRead:
    """Return the user's game profile, creating the default on first use."""
    profile = await game_crud.get_or_create_profile(db, current_user.id)
    rates = await service.load_rates(db)
    await db.commit()
    return _to_profile_read(profile, rates)


@router.post("/events", response_model=GameSyncResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def post_events(
    batch: GameEventBatch,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameSyncResponse:
    """Apply a batch of queued client events; idempotent per client_event_id."""
    # Hoisted: the create-race path rolls back the session, which expires the
    # eager-loaded User — touching current_user.id afterwards would lazy-load.
    user_id = current_user.id
    try:
        profile, results, rates = await service.ingest_events(db, user_id, batch.events)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    applied = sum(1 for r in results if r.status == "applied")
    logger.info(
        "game events ingested: user=%s applied=%d duplicates=%d",
        user_id,
        applied,
        len(results) - applied,
    )
    return GameSyncResponse(
        profile=_to_profile_read(profile, rates),
        results=results,
        applied=applied,
        duplicates=len(results) - applied,
        server_time=datetime.now(timezone.utc),
    )


@router.get("/events", response_model=GameEventsFeedResponse)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_events(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    since: Annotated[Optional[int], Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> GameEventsFeedResponse:
    """Ledger catchup feed: events with id > `since` (the last id the client saw)."""
    rows = await game_crud.get_events_since(db, current_user.id, since, limit)
    return GameEventsFeedResponse(
        events=[GameEventRead.model_validate(row) for row in rows],
        server_time=datetime.now(timezone.utc),
    )
