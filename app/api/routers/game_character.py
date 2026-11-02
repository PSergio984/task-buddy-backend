"""Character sheet endpoints: stat allocation, class pick, respec (issue #64)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_GAME_EVENTS
from app.crud import game as game_crud
from app.dependencies import get_db
from app.game import character_service, engine, service
from app.limiter import limiter
from app.models.user import User
from app.schemas.game import (
    CharacterUpdateIn,
    ClassSelectIn,
    GameProfileRead,
    StatAllocateIn,
)
from app.security import get_confirmed_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/game",
    tags=["game", "character"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
        404: {"description": "Not found"},
    },
)


def _profile_read(profile, rates) -> GameProfileRead:
    return GameProfileRead.from_profile(profile, engine.xp_to_next_level(profile.level, rates))


@router.patch("/character", response_model=GameProfileRead)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def update_character(
    body: CharacterUpdateIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameProfileRead:
    """Toggle auto-distribute; turning it on drains the current unspent pool."""
    user_id = current_user.id
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    profile.auto_allocate = body.auto_allocate
    if body.auto_allocate:
        character_service.distribute_unspent(profile)
    await db.commit()
    rates = await service.load_rates(db)
    return _profile_read(profile, rates)


@router.post("/character/allocate", response_model=GameProfileRead)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def allocate_stats(
    body: StatAllocateIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameProfileRead:
    """Spend unspent stat points; the balance and per-stat cap are enforced."""
    user_id = current_user.id
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    try:
        character_service.allocate_points(profile, body.points)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    rates = await service.load_rates(db)
    logger.info("stats allocated: user=%s points=%s", user_id, body.points)
    return _profile_read(profile, rates)


@router.post("/character/class", response_model=GameProfileRead)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def pick_class(
    body: ClassSelectIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameProfileRead:
    """Pick a class at level 10+; respec re-opens the choice for gold."""
    user_id = current_user.id
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    try:
        character_service.select_class(profile, body.game_class)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Re-pick after respec: owned cross-class gear must not stay worn.
    await character_service.unequip_mismatched(db, user_id, profile.game_class)
    if profile.auto_allocate:
        character_service.distribute_unspent(profile)
    await db.commit()
    rates = await service.load_rates(db)
    logger.info("class picked: user=%s class=%s", user_id, profile.game_class)
    return _profile_read(profile, rates)


@router.post("/character/respec", response_model=GameProfileRead)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def respec_class(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameProfileRead:
    """Pay gold to clear the class and refund allocated points to unspent."""
    user_id = current_user.id
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    rates = await service.load_rates(db)
    try:
        character_service.respec(profile, rates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await character_service.unequip_mismatched(db, user_id, None)
    await db.commit()
    logger.info("class respec: user=%s gold=%s", user_id, profile.gold)
    return _profile_read(profile, rates)
