"""Character sheet endpoints: stat allocation, class pick, respec (issue #64)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_GAME_EVENTS, RATE_LIMIT_GAME_READ
from app.crud import game as game_crud
from app.dependencies import get_db
from app.game import achievements, character_service, engine, service
from app.limiter import limiter
from app.models.user import User
from app.schemas.game import (
    AchievementRead,
    CharacterUpdateIn,
    ClassSelectIn,
    GameProfileRead,
    GearBuyIn,
    GearCostumeIn,
    GearEquipIn,
    GearItemRead,
    GearListResponse,
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
    # 'class-picked' qualifies here, not just on the next scored event.
    await achievements.evaluate(db, user_id, profile)
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


# --- Gear ---------------------------------------------------------------------


def _catalog_read(rows: list[dict]) -> list[GearItemRead]:
    return [GearItemRead.from_row(row) for row in rows]


@router.get("/gear", response_model=list[GearItemRead])
@limiter.limit(RATE_LIMIT_GAME_READ)
async def list_gear(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[GearItemRead]:
    """Full catalog with the viewer's owned/equipped flags merged in."""
    return _catalog_read(await character_service.list_catalog(db, current_user.id))


@router.post("/gear/buy", response_model=GearListResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def buy_gear(
    body: GearBuyIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GearListResponse:
    """Debit gold for a catalog item: class lock, ladder order, balance."""
    user_id = current_user.id
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    await character_service.seed_gear_catalog(db)
    item = await game_crud.get_gear_item(db, body.key)
    if item is None:
        raise HTTPException(status_code=404, detail=f"unknown gear item '{body.key}'")
    try:
        await character_service.buy_gear(db, user_id, profile, item)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 'first-gear' grants on the buy, not on the next scored event.
    await achievements.evaluate(db, user_id, profile)
    await db.commit()
    rates = await service.load_rates(db)
    logger.info("gear bought: user=%s key=%s", user_id, body.key)
    return GearListResponse(
        items=_catalog_read(await character_service.list_catalog(db, user_id)),
        profile=_profile_read(profile, rates),
    )


@router.post("/gear/equip", response_model=GearListResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def equip_gear(
    body: GearEquipIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GearListResponse:
    """Wear or remove an owned item; equipping bumps the slot's occupant."""
    user_id = current_user.id
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    try:
        await character_service.set_equipped(db, user_id, profile, body.key, body.equipped)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    rates = await service.load_rates(db)
    logger.info("gear equipped: user=%s key=%s on=%s", user_id, body.key, body.equipped)
    return GearListResponse(
        items=_catalog_read(await character_service.list_catalog(db, user_id)),
        profile=_profile_read(profile, rates),
    )


@router.post("/gear/costume", response_model=GearListResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def costume_gear(
    body: GearCostumeIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GearListResponse:
    """Show or hide an owned item's look; flagging bumps the slot's costume."""
    user_id = current_user.id
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    try:
        await character_service.set_costume(db, user_id, body.key, body.costume)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    rates = await service.load_rates(db)
    logger.info("gear costume: user=%s key=%s on=%s", user_id, body.key, body.costume)
    return GearListResponse(
        items=_catalog_read(await character_service.list_catalog(db, user_id)),
        profile=_profile_read(profile, rates),
    )


@router.get("/achievements", response_model=list[AchievementRead])
@limiter.limit(RATE_LIMIT_GAME_READ)
async def list_achievements(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AchievementRead]:
    """Every badge in the registry; earned_at fills once granted."""
    rows = await achievements.list_for_user(db, current_user.id)
    return [AchievementRead.from_row(row) for row in rows]
