"""API endpoint for Smart Import extraction (POST /api/v1/import/extract)."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated

import anyio
import openai
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.knowledge import AI_NOT_CONFIGURED, AI_UNAVAILABLE
from app.config import IMPORT_ENABLED, LLM_IMPORT_RESERVE_TOKENS, RATE_LIMIT_IMPORT
from app.crud.import_extract import create_import_answer
from app.crud.project import get_projects
from app.dependencies import get_db
from app.knowledge.assistant import AssistantNotConfiguredError
from app.knowledge.budget import (
    BudgetExceededError,
    reconcile_llm_usage,
    refund_llm_reservation,
    reserve_llm_budget,
)
from app.knowledge.import_extract import build_extract_prompt, generate_extraction
from app.limiter import limiter
from app.models.user import User
from app.schemas.import_extract import ImportExtractRequest, ImportExtractResponse
from app.security import get_confirmed_user

ROUTER_TAG = "import"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={401: {"description": "Not authenticated"}},
)

logger = logging.getLogger(__name__)


@router.post(
    "/import/extract",
    response_model=ImportExtractResponse,
    responses={
        403: {"description": "Email not confirmed"},
        404: {"description": "Import feature is disabled"},
        429: {"description": "Daily AI usage limit reached"},
        503: {"description": AI_NOT_CONFIGURED},
    },
)
@limiter.limit(RATE_LIMIT_IMPORT)
async def import_extract(
    import_in: ImportExtractRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ImportExtractResponse:
    """Extract task proposals from freeform notes (stateless)."""
    if not IMPORT_ENABLED:
        raise HTTPException(status_code=404, detail="Import feature is disabled")

    # Snapshot the user id before the LLM call releases the pooled connection
    # with a rollback that expires every ORM instance (audit #27).
    user_id = current_user.id
    logger.info("POST /import/extract - %s", user_id)

    # Per-user daily spend cap (audit #29; ADR 0002): reserved atomically via
    # a conditional UPDATE that commits before any provider call, so
    # concurrent requests can never oversubscribe the cap.
    try:
        await reserve_llm_budget(db, user_id, LLM_IMPORT_RESERVE_TOKENS)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="Daily AI usage limit reached. Try again tomorrow.",
        ) from exc

    try:
        # Existing projects ground suggested_project_id: names+ids go into the
        # prompt, and the id set filters any hallucinated/foreign ids in the
        # output. Kept inside the try: a failure here would leak the reserved
        # tokens until UTC rollover (phantom 429s).
        projects = await get_projects(db, user_id)
        prompt = build_extract_prompt(
            import_in.text,
            today=datetime.now(timezone.utc).date(),
            projects=[(p.id, p.name) for p in projects],
        )
        valid_project_ids = {p.id for p in projects}

        # Release the pooled connection before the seconds-long LLM call: the
        # rollback expires ORM instances, which is why user_id/project ids were
        # snapshotted above (audit #27 pattern, mirrors breakdown router).
        await db.rollback()

        extraction, record, answer_text, usage_reported = await generate_extraction(
            prompt, valid_project_ids
        )
    except AssistantNotConfiguredError as exc:
        logger.warning("import extraction not configured for user=%s: %s", user_id, exc)
        await refund_llm_reservation(db, user_id, LLM_IMPORT_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except openai.APIError as exc:
        logger.warning("import extraction unavailable for user=%s: %s", user_id, exc)
        await refund_llm_reservation(db, user_id, LLM_IMPORT_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_UNAVAILABLE) from exc
    except asyncio.CancelledError:
        # Disconnect/shutdown skips `except Exception` entirely. The provider
        # call is usually already in flight (tokens consumed server-side), so
        # the estimate stands — release the pooled connection under a shield,
        # then let the cancellation propagate.
        try:
            with anyio.CancelScope(shield=True):
                await db.rollback()
        except Exception:
            logger.exception("import cancellation cleanup failed for user=%s", user_id)
        raise
    except Exception:
        # Any other failure after the reserve would leak the prepaid tokens
        # until UTC rollover (phantom 429s) — refund before propagating. A
        # DB-originated failure poisons the session's transaction, so roll
        # back first; a failing refund must not mask the original error.
        logger.exception("import extraction failed for user=%s", user_id)
        try:
            await db.rollback()
            await refund_llm_reservation(db, user_id, LLM_IMPORT_RESERVE_TOKENS)
        except Exception:
            logger.exception("import reservation refund failed for user=%s", user_id)
        raise

    # Reconcile the reservation to actual spend (flush-only); the final
    # commit below persists it. A provider that omits usage reconciles at the
    # reserved amount (conservative, never under-bills — the usage_reported
    # convention from the ask stream, assistant.py).
    actual = record.total_tokens or LLM_IMPORT_RESERVE_TOKENS
    await reconcile_llm_usage(db, user_id, LLM_IMPORT_RESERVE_TOKENS, actual)
    await create_import_answer(
        db,
        user_id=user_id,
        answer_text=answer_text,
        record=record,
        input_chars=len(import_in.text),
    )
    await db.commit()
    return ImportExtractResponse(proposals=extraction.proposals, reason=extraction.reason)
