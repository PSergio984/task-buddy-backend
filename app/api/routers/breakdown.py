"""API endpoint for the task-breakdown bot (POST /api/v1/breakdown)."""

import logging
from typing import Annotated, Optional

import openai
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.knowledge import AI_NOT_CONFIGURED, AI_UNAVAILABLE
from app.config import BREAKDOWN_ENABLED, RATE_LIMIT_BREAKDOWN
from app.crud.breakdown import create_breakdown_answer
from app.dependencies import get_db
from app.knowledge.assistant import AssistantNotConfiguredError
from app.knowledge.breakdown import (
    build_breakdown_prompt,
    fetch_memory_hints,
    generate_breakdown,
)
from app.knowledge.budget import BudgetExceededError, check_llm_budget
from app.limiter import limiter
from app.models.task import Task
from app.models.user import User
from app.schemas.breakdown import BreakdownRequest, BreakdownResponse
from app.security import get_confirmed_user

ROUTER_TAG = "breakdown"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={401: {"description": "Not authenticated"}},
)

logger = logging.getLogger(__name__)


@router.post(
    "/breakdown",
    response_model=BreakdownResponse,
    responses={
        404: {"description": "Breakdown feature is disabled"},
        503: {"description": AI_NOT_CONFIGURED},
    },
)
@limiter.limit(RATE_LIMIT_BREAKDOWN)
async def breakdown(
    breakdown_in: BreakdownRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BreakdownResponse:
    """Propose a task/subtask breakdown for the given text (stateless)."""
    if not BREAKDOWN_ENABLED:
        raise HTTPException(status_code=404, detail="Breakdown feature is disabled")

    # Snapshot the user id before the LLM call releases the pooled connection
    # with a rollback that expires every ORM instance (audit #27).
    user_id = current_user.id
    logger.info("POST /breakdown - %s", user_id)

    # Per-user daily spend cap — checked before any LLM call (audit #29).
    try:
        await check_llm_budget(db, user_id)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="Daily AI usage limit reached. Try again tomorrow.",
        ) from exc

    context_task_id: Optional[int] = None
    context_title: Optional[str] = None
    context_description: Optional[str] = None
    if breakdown_in.context_task_id is not None:
        result = await db.execute(
            select(Task).where(Task.id == breakdown_in.context_task_id, Task.user_id == user_id)
        )
        context_task = result.scalar_one_or_none()
        if context_task is not None:
            context_task_id = context_task.id
            context_title = context_task.title
            context_description = context_task.description

    memory_hints = await fetch_memory_hints(db, user_id, breakdown_in.text)
    prompt = build_breakdown_prompt(
        breakdown_in.text,
        context_title=context_title,
        context_description=context_description,
        memory_hints=memory_hints,
        focus_task_title=breakdown_in.focus_task_title,
        focus_task_number=breakdown_in.focus_task_number,
    )

    # Release the pooled connection before the seconds-long LLM call: the
    # rollback expires ORM instances, which is why user_id/context fields were
    # snapshotted above (audit #27 pattern, mirrors planner service).
    await db.rollback()

    try:
        proposal, record, answer_text = await generate_breakdown(prompt)
    except AssistantNotConfiguredError as exc:
        logger.warning("breakdown not configured for user=%s: %s", user_id, exc)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except openai.APIError as exc:
        logger.warning("breakdown unavailable for user=%s: %s", user_id, exc)
        raise HTTPException(status_code=503, detail=AI_UNAVAILABLE) from exc

    await create_breakdown_answer(
        db,
        user_id=user_id,
        answer_text=answer_text,
        record=record,
        input_chars=len(breakdown_in.text),
        context_task_id=context_task_id,
    )
    await db.commit()
    return BreakdownResponse(tasks=proposal.tasks, reason=proposal.reason)
