"""Daily CRUD + check endpoints: recurring checklist items with streaks."""

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_GAME_EVENTS, RATE_LIMIT_GAME_READ
from app.crud import game as game_crud
from app.dependencies import get_db
from app.game import achievements, character_service, daily_service, engine, service
from app.limiter import limiter
from app.models.game import Daily, DailyItem
from app.models.user import User
from app.schemas.game import (
    DailyCheckIn,
    DailyCheckResponse,
    DailyIn,
    DailyRead,
    DailyUpdate,
    GameProfileRead,
)
from app.security import get_confirmed_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/game/dailies",
    tags=["game", "dailies"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
        404: {"description": "Not found"},
    },
)


async def _profile_read(db: AsyncSession, profile, rates) -> GameProfileRead:
    return GameProfileRead.from_profile(
        profile,
        engine.xp_to_next_level(profile.level, rates),
        await character_service.gear_stat_bonus(db, profile.user_id),
    )


async def _owned_daily(db: AsyncSession, user_id: int, daily_id: int) -> Daily:
    daily = await game_crud.get_daily(db, user_id, daily_id)
    if daily is None:
        raise HTTPException(status_code=404, detail="Daily not found")
    return daily


async def _daily_reads(db: AsyncSession, dailies: list[Daily], today: date) -> list[DailyRead]:
    """DailyRead list with checklists and today's completion flags filled in."""
    daily_ids = [d.id for d in dailies]
    items = await game_crud.list_daily_items(db, daily_ids)
    checks = await game_crud.list_daily_checks(db, daily_ids, today, today)
    items_by_daily: dict[int, list[DailyItem]] = {}
    for item in items:
        items_by_daily.setdefault(item.daily_id, []).append(item)
    done_items: dict[int, set[int]] = {}
    master_done: set[int] = set()
    for check in checks:
        if not check.done:
            continue
        if check.daily_item_id is None:
            master_done.add(check.daily_id)
        else:
            done_items.setdefault(check.daily_id, set()).add(check.daily_item_id)
    return [
        DailyRead.from_rows(
            daily,
            items_by_daily.get(daily.id, []),
            done_items.get(daily.id, set()),
            daily.id in master_done,
        )
        for daily in dailies
    ]


async def _daily_read(db: AsyncSession, daily: Daily, today: date) -> DailyRead:
    return (await _daily_reads(db, [daily], today))[0]


def _item_rows(daily_id: int, items_in: list[dict]) -> list[DailyItem]:
    """Checklist rows for a write; missing positions default to list order.

    Takes model_dump dicts (the PATCH path) — attribute access would fail.
    """
    return [
        DailyItem(
            daily_id=daily_id,
            title=item["title"],
            position=item["position"] if item.get("position") is not None else i,
        )
        for i, item in enumerate(items_in)
    ]


@router.post("", response_model=DailyRead, status_code=201)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def create_daily(
    daily_in: DailyIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DailyRead:
    user_id = current_user.id
    today = datetime.now(timezone.utc).date()
    # Same serialization point as habits: the profile lock makes the count
    # check exact against concurrent creates.
    await game_crud.get_or_create_profile(db, user_id, for_update=True)
    if await game_crud.count_dailies(db, user_id) >= daily_service.MAX_DAILIES_PER_USER:
        raise HTTPException(status_code=400, detail="Daily limit reached")
    daily = Daily(
        user_id=user_id,
        title=daily_in.title,
        notes=daily_in.notes,
        difficulty=daily_in.difficulty,
        recurrence=daily_service.recurrence_for_storage(
            daily_in.recurrence.model_dump(mode="json", exclude_none=True), today
        ),
        reminder_times=daily_in.reminder_times,
    )
    db.add(daily)
    await db.flush()  # populate daily.id before the item rows need it
    db.add_all(_item_rows(daily.id, [i.model_dump() for i in daily_in.items]))
    await db.commit()
    logger.info("daily created: user=%s daily=%s", user_id, daily.id)
    return await _daily_read(db, daily, today)


@router.get("", response_model=list[DailyRead])
@limiter.limit(RATE_LIMIT_GAME_READ)
async def list_dailies(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[DailyRead]:
    """All of the user's dailies with checklists and today's completion."""
    today = datetime.now(timezone.utc).date()
    dailies = await game_crud.list_dailies(db, current_user.id)
    return await _daily_reads(db, dailies, today)


@router.get("/{daily_id}", response_model=DailyRead)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_daily(
    daily_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DailyRead:
    daily = await _owned_daily(db, current_user.id, daily_id)
    return await _daily_read(db, daily, datetime.now(timezone.utc).date())


@router.patch(
    "/{daily_id}",
    response_model=DailyRead,
    responses={400: {"description": "No fields to update"}},
)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def update_daily(
    daily_id: int,
    daily_in: DailyUpdate,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DailyRead:
    # mode="json": a nested date (every_n_days anchor) must serialize into
    # the JSONB recurrence blob — python mode would leave datetime.date in
    # the payload and fail JSON encoding at commit.
    update_data = daily_in.model_dump(mode="json", exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    today = datetime.now(timezone.utc).date()
    # Hoisted before the lock: a create-race rollback expires current_user.
    user_id = current_user.id
    # Serialize against in-flight checks: a PATCH mid-flight must not race a
    # scored check's streak/share read or strand on a deleted row.
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    daily = await _owned_daily(db, user_id, daily_id)
    items_in = update_data.pop("items", None)
    if "recurrence" in update_data:
        update_data["recurrence"] = daily_service.recurrence_for_storage(
            update_data["recurrence"], today
        )
    for field, value in update_data.items():
        setattr(daily, field, value)
    if items_in is not None:
        # Full replace — removed items cascade their check marks, so a
        # mid-day replace can only widen the master's remaining share.
        await db.execute(delete(DailyItem).where(DailyItem.daily_id == daily.id))
        db.add_all(_item_rows(daily.id, items_in))
    # Only due-SHRINKING edits can newly qualify a past day for
    # perfect-day: a narrower recurrence or deactivation removes a daily
    # from due sets it used to block. Reactivating/widening can't grant,
    # and no ledger row lands here, so reopen the daily gate explicitly —
    # the event-gated eval would otherwise wait for the next check.
    if "recurrence" in update_data or update_data.get("active") is False:
        await achievements.evaluate(db, user_id, profile, event_types={"daily_check"})
    await db.commit()
    await db.refresh(daily)
    logger.info("daily updated: user=%s daily=%s", user_id, daily.id)
    return await _daily_read(db, daily, today)


@router.delete("/{daily_id}")
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def delete_daily(
    daily_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    # Serialize against in-flight checks — same lock order as habits.
    user_id = current_user.id
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    daily = await _owned_daily(db, user_id, daily_id)
    await db.delete(daily)
    # Deleting shrinks the due-set for every past date — a day that was
    # short one unchecked daily may now be perfect. Same daily-gate reopen
    # as PATCH: no ledger row lands on a delete.
    await achievements.evaluate(db, user_id, profile, event_types={"daily_check"})
    await db.commit()
    logger.info("daily deleted: user=%s daily=%s", user_id, daily_id)
    return {"message": "Daily deleted successfully"}


@router.post("/{daily_id}/check", response_model=DailyCheckResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def check_daily(
    daily_id: int,
    check_in: DailyCheckIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DailyCheckResponse:
    """Score one check: proportional XP+gold plus the streak gold bonus.

    Omit daily_item_id to check the whole daily (pays the remaining share);
    check_date backfills an offline day. Idempotent per client_event_id, and
    per (daily, item, day) — a repeated check records unscored, never pays
    twice. Offline clients get the same path by queueing daily_check events
    to /game/events.
    """
    user_id = current_user.id
    now = datetime.now(timezone.utc)
    today = now.date()
    # Lock first (per-user serialization point), then read mutable state —
    # identical ordering to habit clicks.
    profile = await game_crud.get_or_create_profile(db, user_id, for_update=True)
    daily = await _owned_daily(db, user_id, daily_id)
    rates = await service.load_rates(db)
    if check_in.client_event_id is not None:
        seen = await game_crud.existing_event_ids(db, user_id, [check_in.client_event_id])
        if check_in.client_event_id in seen:
            return DailyCheckResponse(
                daily=await _daily_read(db, daily, today),
                profile=await _profile_read(db, profile, rates),
                status="duplicate",
                server_time=now,
            )
    check_date = check_in.check_date or today
    eid = check_in.client_event_id or f"server:daily:{daily.id}:check:{uuid.uuid4().hex}"
    items = await game_crud.list_daily_items(db, [daily.id])
    try:
        await daily_service.score_check(
            db,
            daily,
            items,
            check_in.daily_item_id,
            check_date,
            profile,
            rates,
            today,
            eid=eid,
            client_ts=now,
            done=check_in.done,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await character_service.post_score(db, user_id, profile, event_types={"daily_check"})
    await db.commit()
    await db.refresh(daily)
    logger.info(
        "daily checked: user=%s daily=%s item=%s date=%s",
        user_id,
        daily.id,
        check_in.daily_item_id,
        check_date,
    )
    return DailyCheckResponse(
        daily=await _daily_read(db, daily, today),
        profile=await _profile_read(db, profile, rates),
        status="applied",
        server_time=now,
    )
