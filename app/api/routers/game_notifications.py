"""Notification prefs + device-token endpoints for the game layer (issue #68)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_GAME_EVENTS, RATE_LIMIT_GAME_READ
from app.crud import game as game_crud
from app.dependencies import get_db
from app.game import notifications as game_notifications
from app.limiter import limiter
from app.models.user import User
from app.schemas.game import (
    DeviceTokenIn,
    DeviceTokenRead,
    NotificationPrefsIn,
    NotificationPrefsRead,
    QuietHoursIn,
)
from app.security import get_confirmed_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/game",
    tags=["game", "notifications"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
        404: {"description": "Not found"},
    },
)


def _prefs_read(pref) -> NotificationPrefsRead:
    """Stored row -> the full effective matrix (defaults fill every gap).

    A stored blob that fails re-validation (only reachable via out-of-band
    writes — PUT validates) collapses to defaults instead of 500ing reads.
    """
    stored = (pref.prefs if pref else None) or {}
    prefs = {
        key: {**game_notifications.DEFAULT_CHANNELS, **(stored.get(key) or {})}
        for key in sorted(game_notifications.KIND_KEYS)
    }
    quiet = {**game_notifications.DEFAULT_QUIET, **((pref.quiet_hours or {}) if pref else {})}
    try:
        quiet_model = QuietHoursIn(**quiet)
    except ValidationError:
        quiet_model = QuietHoursIn()
    return NotificationPrefsRead(prefs=prefs, quiet_hours=quiet_model)


@router.get("/notification-prefs", response_model=NotificationPrefsRead)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_notification_prefs(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationPrefsRead:
    """The type×channel matrix + quiet window; defaults when no row exists."""
    return _prefs_read(await game_crud.get_notification_pref(db, current_user.id))


@router.put("/notification-prefs", response_model=NotificationPrefsRead)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def put_notification_prefs(
    body: NotificationPrefsIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationPrefsRead:
    """Replace the whole prefs object; returns the saved effective matrix."""
    pref = await game_crud.save_notification_pref(
        db,
        current_user.id,
        prefs={k: dict(v) for k, v in body.prefs.items()},
        quiet_hours=body.quiet_hours.model_dump(),
    )
    await db.commit()
    return _prefs_read(pref)


@router.post("/device-tokens", response_model=DeviceTokenRead, status_code=201)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def register_device_token(
    body: DeviceTokenIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DeviceTokenRead:
    """Register (upsert on token) a push-delivery device token for the user."""
    row = await game_crud.upsert_device_token(db, current_user.id, body.platform, body.token)
    await db.commit()
    return DeviceTokenRead.model_validate(row)


@router.delete("/device-tokens/{token}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def delete_device_token(
    token: str,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Unregister a device token; owner-scoped, 404 when absent."""
    deleted = await game_crud.delete_device_token(db, current_user.id, token)
    if not deleted:
        raise HTTPException(status_code=404, detail="Device token not found")
    await db.commit()
    return None
