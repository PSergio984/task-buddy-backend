"""Habit CRUD + click endpoints: +/- counters with drift and focus binding."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_GAME_EVENTS, RATE_LIMIT_GAME_READ
from app.crud import game as game_crud
from app.dependencies import get_db
from app.game import engine, habit_service, service
from app.limiter import limiter
from app.models.game import Habit, HabitDirection
from app.models.user import User
from app.schemas.game import (
    GameProfileRead,
    HabitClickIn,
    HabitClickResponse,
    HabitIn,
    HabitRead,
    HabitUpdate,
)
from app.security import get_confirmed_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/game/habits",
    tags=["game", "habits"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
        404: {"description": "Not found"},
    },
)


def _profile_read(profile, rates) -> GameProfileRead:
    return GameProfileRead.from_profile(profile, engine.xp_to_next_level(profile.level, rates))


async def _owned_habit(db: AsyncSession, user_id: int, habit_id: int) -> Habit:
    habit = await game_crud.get_habit(db, user_id, habit_id)
    if habit is None:
        raise HTTPException(status_code=404, detail="Habit not found")
    return habit


@router.post("", response_model=HabitRead, status_code=201)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def create_habit(
    habit_in: HabitIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HabitRead:
    user_id = current_user.id
    # The profile lock serializes creates against each other and against
    # scoring, so the count check is exact; the cap bounds the per-phase
    # auto-click fanout.
    await game_crud.get_or_create_profile(db, user_id, for_update=True)
    if len(await game_crud.list_habits(db, user_id)) >= habit_service.MAX_HABITS_PER_USER:
        raise HTTPException(status_code=400, detail="Habit limit reached")
    habit = Habit(
        user_id=user_id,
        title=habit_in.title,
        notes=habit_in.notes,
        direction=HabitDirection(habit_in.direction),
        difficulty=habit_in.difficulty,
        reminder_times=habit_in.reminder_times,
        bind_focus=habit_in.bind_focus,
    )
    db.add(habit)
    await db.commit()
    logger.info("habit created: user=%s habit=%s", user_id, habit.id)
    return HabitRead.model_validate(habit)


@router.get("", response_model=list[HabitRead])
@limiter.limit(RATE_LIMIT_GAME_READ)
async def list_habits(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[HabitRead]:
    """All of the user's habits in creation order."""
    rows = await game_crud.list_habits(db, current_user.id)
    return [HabitRead.model_validate(row) for row in rows]


@router.get("/{habit_id}", response_model=HabitRead)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_habit(
    habit_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HabitRead:
    return HabitRead.model_validate(await _owned_habit(db, current_user.id, habit_id))


@router.patch(
    "/{habit_id}",
    response_model=HabitRead,
    responses={400: {"description": "No fields to update"}},
)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def update_habit(
    habit_id: int,
    habit_in: HabitUpdate,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HabitRead:
    update_data = habit_in.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    # Hoisted before the lock: a create-race rollback in get_or_create_profile
    # expires every session object, including current_user.
    user_id = current_user.id
    # Same serialization as click/delete: a PATCH mid-flight must not race a
    # scored click's direction/difficulty read or strand on a deleted row.
    await game_crud.get_or_create_profile(db, user_id, for_update=True)
    habit = await _owned_habit(db, user_id, habit_id)
    for field, value in update_data.items():
        if field == "direction":
            value = HabitDirection(value)
        setattr(habit, field, value)
    await db.commit()
    # updated_at is an onupdate column — expired post-commit, refetch it.
    await db.refresh(habit)
    logger.info("habit updated: user=%s habit=%s", user_id, habit.id)
    return HabitRead.model_validate(habit)


@router.delete("/{habit_id}")
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def delete_habit(
    habit_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    # Serialize against in-flight clicks: every scoring path holds this lock
    # while updating the habit row — an unlocked delete could strand the
    # concurrent UPDATE (StaleDataError -> 500).
    user_id = current_user.id
    await game_crud.get_or_create_profile(db, user_id, for_update=True)
    habit = await _owned_habit(db, user_id, habit_id)
    await db.delete(habit)
    await db.commit()
    logger.info("habit deleted: user=%s habit=%s", user_id, habit_id)
    return {"message": "Habit deleted successfully"}


@router.post("/{habit_id}/click", response_model=HabitClickResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def click_habit(
    habit_id: int,
    click_in: HabitClickIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HabitClickResponse:
    """Score one click through the engine; idempotent per client_event_id.

    + clicks pay drift-scaled XP+gold, - clicks cost HP only; the stored
    value drifts per the Habitica formula. Offline clients get the same
    scoring by queueing habit_click events to /game/events instead.
    """
    user_id = current_user.id
    # Lock first (per-user serialization point), then read mutable state:
    # the habit snapshot, the dedupe check and the write-back all happen
    # under the lock so same-eid replays dedupe and parallel clicks
    # serialize instead of IntegrityError-500ing or double-scoring.
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    habit = await _owned_habit(db, user_id, habit_id)
    rates = await service.load_rates(db)
    if click_in.client_event_id is not None:
        seen = await game_crud.existing_event_ids(db, user_id, [click_in.client_event_id])
        if click_in.client_event_id in seen:
            return HabitClickResponse(
                habit=HabitRead.model_validate(habit),
                profile=_profile_read(profile, rates),
                status="duplicate",
                server_time=datetime.now(timezone.utc),
            )
    try:
        habit_service.check_direction(habit, click_in.direction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    now = datetime.now(timezone.utc)
    # A client-supplied id dedupes offline replays of the same click; absent
    # one the server mints its own under the reserved "server:" namespace.
    eid = click_in.client_event_id or f"server:habit:{habit.id}:{uuid.uuid4().hex}"
    await habit_service.score_click(
        db,
        habit,
        click_in.direction,
        profile,
        rates,
        now.date(),
        eid=eid,
        client_ts=now,
    )
    await db.commit()
    # updated_at is an onupdate column — expired post-commit, refetch it.
    await db.refresh(habit)
    logger.info(
        "habit clicked: user=%s habit=%s direction=%s", user_id, habit.id, click_in.direction
    )
    return HabitClickResponse(
        habit=HabitRead.model_validate(habit),
        profile=_profile_read(profile, rates),
        status="applied",
        server_time=now,
    )
