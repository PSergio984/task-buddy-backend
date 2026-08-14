"""API endpoint for the planner (POST /api/v1/plan)."""

import logging
from typing import Annotated

import openai
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.knowledge import AI_NOT_CONFIGURED, AI_UNAVAILABLE
from app.config import RATE_LIMIT_PLAN, SYNTHETIC_CALENDAR_ENABLED
from app.dependencies import get_db
from app.knowledge.assistant import AssistantNotConfiguredError
from app.limiter import limiter
from app.models.user import User
from app.planner.connector import SyntheticCalendarConnector
from app.planner.service import create_plan
from app.schemas.plan import PlanRequest, PlanResponse
from app.security import get_confirmed_user

ROUTER_TAG = "plan"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={401: {"description": "Not authenticated"}},
)

logger = logging.getLogger(__name__)


@router.post(
    "/plan", response_model=PlanResponse, responses={503: {"description": AI_NOT_CONFIGURED}}
)
@limiter.limit(RATE_LIMIT_PLAN)
async def plan(
    plan_in: PlanRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlanResponse:
    """Return a ranked, time-bucketed plan across the user's open tasks."""
    logger.info("POST /plan - %s", current_user.id)

    connector = SyntheticCalendarConnector() if SYNTHETIC_CALENDAR_ENABLED else None
    try:
        result = await create_plan(
            db,
            current_user.id,
            plan_in.available_minutes,
            plan_in.limit,
            connector,
        )
    except AssistantNotConfiguredError as exc:
        logger.warning("plan not configured for user=%s: %s", current_user.id, exc)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except openai.APIError as exc:
        logger.warning("plan unavailable for user=%s: %s", current_user.id, exc)
        raise HTTPException(status_code=503, detail=AI_UNAVAILABLE) from exc

    await db.commit()
    return result
