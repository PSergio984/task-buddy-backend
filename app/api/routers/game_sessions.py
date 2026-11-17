"""Focus-session lifecycle: start / pause / resume / advance / stop / done / reads.

Every call replays elapsed wall-clock transitions inside a locked transaction,
so a session left mid-phase completes (or ends) itself deterministically — the
app being closed can neither cheat nor lose state.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_GAME_EVENTS, RATE_LIMIT_GAME_READ
from app.crud import game as game_crud
from app.database import AsyncSessionLocal
from app.dependencies import get_db
from app.game import character_service, engine, session_engine as se, session_service
from app.limiter import limiter
from app.models.game import GameEvent
from app.models.user import User
from app.schemas.game import (
    DiversionPenaltyIn,
    DiversionPenaltyOut,
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


async def _profile_read(db: AsyncSession, profile, rates) -> GameProfileRead | None:
    if profile is None:
        return None
    return GameProfileRead.from_profile(
        profile,
        engine.xp_to_next_level(profile.level, rates),
        await character_service.gear_stat_bonus(db, profile.user_id),
    )


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
            # A scalar-JSON blob (DB-surgery only — the API only ever writes
            # dicts) can't 500 the read endpoints' response validation.
            speedrun=session.speedrun if isinstance(session.speedrun, dict) else None,
            phone_down=(session.phone_down if isinstance(session.phone_down, dict) else None),
            phases=phases,
        ),
        profile=await _profile_read(db, profile, rates),
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


@router.post("/diversion", response_model=DiversionPenaltyOut)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def record_diversion(
    body: DiversionPenaltyIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DiversionPenaltyOut:
    """Record a desktop barrier diversion penalty, calculating HP loss with gear defense mitigation."""
    user_id = current_user.id
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    rates = await session_service.load_rates(db)
    stat_bonus = await character_service.gear_stat_bonus(db, user_id)

    outcome = engine.apply_hp_loss(profile, body.base_damage, rates, stat_bonus=stat_bonus)
    hp_lost = outcome.get("hp_lost", 0.0)
    mitigated = max(0.0, float(body.base_damage) - float(hp_lost))

    # Log diversion penalty event in game ledger
    now = datetime.now(timezone.utc)
    event = GameEvent(
        user_id=user_id,
        client_event_id=f"server:diversion:{user_id}:{int(now.timestamp())}",
        type="diversion_penalty",
        payload={
            "session_id": body.session_id,
            "reason": body.reason,
            "base_damage": body.base_damage,
            "hp_lost": hp_lost,
            "damage_mitigated": mitigated,
        },
        client_ts=now,
        server_ts=now,
    )
    db.add(event)
    await db.commit()

    logger.info(
        "diversion penalty applied: user=%s base=%s lost=%s mitigated=%s hp=%s died=%s",
        user_id,
        body.base_damage,
        hp_lost,
        mitigated,
        profile.hp,
        outcome.get("died", False),
    )

    return DiversionPenaltyOut(
        applied=True,
        base_damage=body.base_damage,
        hp_lost=hp_lost,
        damage_mitigated=mitigated,
        current_hp=profile.hp,
        died=outcome.get("died", False),
        gear_stat_bonus=stat_bonus,
    )


@router.get("/stream")
async def session_stream(
    request: Request,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    heartbeat_seconds: int = 15,
    once: bool = False,
) -> StreamingResponse:
    """Server-Sent Events stream for real-time focus session state synchronization."""
    user_id = current_user.id

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                result = await session_service.get_active_view(db, user_id)
                await db.commit()
                if result is not None:
                    f_session, phases, _ = result
                    active_phase = se.live_phase(phases)
                    phase_data = (
                        {
                            "seq": active_phase.seq,
                            "kind": active_phase.kind,
                            "status": active_phase.status,
                            "minutes": active_phase.minutes,
                        }
                        if active_phase
                        else None
                    )
                    payload = {
                        "is_active": True,
                        "session_id": f_session.id,
                        "task_id": f_session.task_id,
                        "activity_label": f_session.activity_label,
                        "mode": f_session.mode,
                        "status": f_session.status,
                        "current_phase": phase_data,
                        "server_time": datetime.now(timezone.utc).isoformat(),
                    }
                else:
                    payload = {
                        "is_active": False,
                        "session_id": None,
                        "task_id": None,
                        "activity_label": None,
                        "mode": None,
                        "status": "idle",
                        "current_phase": None,
                        "server_time": datetime.now(timezone.utc).isoformat(),
                    }

                yield f"event: session_state\ndata: {json.dumps(payload)}\n\n"

                if once:
                    break

                # Check for disconnection rapidly (every 500ms) rather than blocking on long sleep
                disconnected = False
                for _ in range(max(1, heartbeat_seconds * 2)):
                    if await request.is_disconnected():
                        disconnected = True
                        break
                    await asyncio.sleep(0.5)

                if disconnected:
                    break
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    """End now: mid-phase with 0 completed focus phases -> HP loss;
    speedrun: always abandon + HP."""
    result = await _run(db, current_user.id, session_id, session_service.stop)
    await db.commit()
    return await _respond(db, result)


@router.post("/{session_id}/done", response_model=SessionActionResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def done(
    session_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionActionResponse:
    """User-declared finish — the speedrun win path (400 on other modes)."""
    result = await _run(db, current_user.id, session_id, session_service.done)
    await db.commit()
    return await _respond(db, result)
