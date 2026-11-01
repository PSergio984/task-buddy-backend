"""Focus-session lifecycle: start / pause / resume / advance / stop / reads.

Every call replays elapsed wall-clock transitions inside a locked transaction,
so a session left mid-phase completes (or ends) itself deterministically — the
app being closed can neither cheat nor lose state.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_GAME_EVENTS, RATE_LIMIT_GAME_READ
from app.dependencies import get_db
from app.game import engine, session_service
from app.limiter import limiter
from app.models.user import User
from app.schemas.game import (
    FocusSessionOut,
    GameProfileRead,
    SessionActionResponse,
    SessionStartIn,
)
from app.security import get_confirmed_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/game/sessions",
    tags=["game", "focus-sessions"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
        404: {"description": "Not found"},
        409: {"description": "Conflict"},
    },
)


def _profile_read(profile, rates) -> GameProfileRead | None:
    if profile is None:
        return None
    return GameProfileRead.from_profile(profile, engine.xp_to_next_level(profile.level, rates))


async def _respond(db, result) -> SessionActionResponse:
    session, phases, profile = result
    rates = await session_service.load_rates(db)
    return SessionActionResponse(
        session=FocusSessionOut(
            id=session.id,
            mode=session.mode,
            status=session.status,
            task_id=session.task_id,
            activity_label=session.activity_label,
            preset=session.preset,
            pause_budget_count=session.pause_budget_count,
            pause_budget_seconds=session.pause_budget_seconds,
            started_at=session.started_at,
            ended_at=session.ended_at,
            phases=phases,
        ),
        profile=_profile_read(profile, rates),
        server_time=datetime.now(timezone.utc),
    )


async def _run(db, user_id, session_id, fn):
    """Shared action error mapping: ValueError -> 400, conflicts -> 409."""
    try:
        result = await fn(db, user_id, session_id)
        logger.info("session %s %s: user=%s", session_id, fn.__name__, user_id)
        return result
    except session_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except session_service.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=SessionActionResponse, status_code=201)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def start_session(
    body: SessionStartIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionActionResponse:
    """Open a session; 409 when one is already active."""
    user_id = current_user.id
    try:
        result = await session_service.start_session(db, user_id, body)
    except session_service.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except session_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    logger.info("focus session started: user=%s session=%s", user_id, result[0].id)
    return await _respond(db, result)


@router.get("/active", response_model=SessionActionResponse | None)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_active(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionActionResponse | None:
    """The in-flight session after wall-clock evaluation, or null."""
    result = await session_service.get_active_view(db, current_user.id)
    if result is None:
        return None
    await db.commit()
    return await _respond(db, result)


@router.get("/{session_id}", response_model=SessionActionResponse)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_session(
    session_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionActionResponse:
    """One session by id (evaluated), owner-scoped."""
    result = await _run(db, current_user.id, session_id, session_service.get_view)
    await db.commit()
    return await _respond(db, result)


@router.post("/{session_id}/pause", response_model=SessionActionResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def pause(
    session_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionActionResponse:
    result = await _run(db, current_user.id, session_id, session_service.pause)
    await db.commit()
    return await _respond(db, result)


@router.post("/{session_id}/resume", response_model=SessionActionResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def resume(
    session_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionActionResponse:
    result = await _run(db, current_user.id, session_id, session_service.resume)
    await db.commit()
    return await _respond(db, result)


@router.post("/{session_id}/advance", response_model=SessionActionResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def advance(
    session_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionActionResponse:
    """Tap-into-next: begin the pending focus phase or skip a running break."""
    result = await _run(db, current_user.id, session_id, session_service.advance)
    await db.commit()
    return await _respond(db, result)


@router.post("/{session_id}/stop", response_model=SessionActionResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def stop(
    session_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionActionResponse:
    """End now: mid-phase with 0 completed focus phases -> HP loss."""
    result = await _run(db, current_user.id, session_id, session_service.stop)
    await db.commit()
    return await _respond(db, result)
