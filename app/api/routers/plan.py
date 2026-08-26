"""API endpoint for the planner (POST /api/v1/plan)."""

import logging
from typing import Annotated

import openai
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.knowledge import AI_NOT_CONFIGURED, AI_UNAVAILABLE
from app.config import LLM_PLAN_RESERVE_TOKENS, RATE_LIMIT_PLAN, SYNTHETIC_CALENDAR_ENABLED
from app.dependencies import get_db
from app.knowledge.assistant import AssistantNotConfiguredError
from app.knowledge.budget import (
    BudgetExceededError,
    reconcile_llm_usage,
    refund_llm_reservation,
    reserve_llm_budget,
)
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
    # Snapshot the user id: create_plan releases the pooled connection with a
    # rollback that expires every ORM instance — any later attribute access on
    # current_user (e.g. logging) would trigger a lazy refresh outside a
    # greenlet context (audit #27).
    user_id = current_user.id
    logger.info("POST /plan - %s", user_id)

    # Per-user daily spend cap (audit #29; ADR 0002): reserved atomically via
    # a conditional UPDATE that commits before any provider call, so
    # concurrent requests can never oversubscribe the cap.
    try:
        await reserve_llm_budget(db, user_id, LLM_PLAN_RESERVE_TOKENS)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="Daily AI usage limit reached. Try again tomorrow.",
        ) from exc

    connector = SyntheticCalendarConnector() if SYNTHETIC_CALENDAR_ENABLED else None
    try:
        result = await create_plan(
            db,
            user_id,
            plan_in.available_minutes,
            plan_in.limit,
            connector,
        )
    except AssistantNotConfiguredError as exc:
        logger.warning("plan not configured for user=%s: %s", user_id, exc)
        await refund_llm_reservation(db, user_id, LLM_PLAN_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except openai.APIError as exc:
        logger.warning("plan unavailable for user=%s: %s", user_id, exc)
        await refund_llm_reservation(db, user_id, LLM_PLAN_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_UNAVAILABLE) from exc
    except RuntimeError as exc:
        # Embedding path raises RuntimeError when the OpenAI key is missing.
        logger.warning("plan not configured (embeddings) user=%s: %s", user_id, exc)
        await refund_llm_reservation(db, user_id, LLM_PLAN_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc

    # Reconcile the reservation to actual spend (flush-only); the final
    # commit below persists it.
    await reconcile_llm_usage(db, user_id, LLM_PLAN_RESERVE_TOKENS, result.total_tokens)
    await db.commit()
    return result
