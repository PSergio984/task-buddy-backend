"""API endpoint for Smart Import extraction (POST /api/v1/import/extract)."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any

import anyio
import openai
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.knowledge import AI_NOT_CONFIGURED, AI_UNAVAILABLE
from app.config import IMPORT_ENABLED, LLM_IMPORT_RESERVE_TOKENS, RATE_LIMIT_IMPORT
from app.crud import knowledge as knowledge_crud
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
from app.knowledge.ingest import ingest_knowledge
from app.knowledge.retrieval import UserKnowledgeIndex
from app.limiter import limiter
from app.models.knowledge import KnowledgeChunk, SourceType, TaskKnowledge
from app.models.user import User
from app.schemas.import_extract import ImportExtractRequest, ImportExtractResponse
from app.security import get_confirmed_user

ROUTER_TAG = "import"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={401: {"description": "Not authenticated"}},
)

logger = logging.getLogger(__name__)


async def _validate_source_knowledge(
    db: AsyncSession, source_knowledge_id: int | None, user_id: int
) -> None:
    if source_knowledge_id is not None:
        existing = await knowledge_crud.get_knowledge(db, source_knowledge_id, user_id)
        if not existing or existing.source_type != SourceType.NOTE or existing.task_id is not None:
            raise HTTPException(status_code=400, detail="Invalid source_knowledge_id")


async def _perform_extraction(db: AsyncSession, user_id: int, text: str) -> tuple[Any, Any, str]:
    """Perform prompt build, connection release, and LLM extraction with error handling."""
    provider_started = False
    try:
        projects = await get_projects(db, user_id)
        prompt = build_extract_prompt(
            text,
            today=datetime.now(timezone.utc).date(),
            projects=[(p.id, p.name) for p in projects],
        )
        valid_project_ids = {p.id for p in projects}
        await db.rollback()

        provider_started = True
        extraction, record, answer_text, _ = await generate_extraction(prompt, valid_project_ids)
        return extraction, record, answer_text
    except AssistantNotConfiguredError as exc:
        logger.warning("import extraction not configured for user=%s: %s", user_id, exc)
        await refund_llm_reservation(db, user_id, LLM_IMPORT_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except openai.APIError as exc:
        logger.warning("import extraction unavailable for user=%s: %s", user_id, exc)
        await refund_llm_reservation(db, user_id, LLM_IMPORT_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_UNAVAILABLE) from exc
    except asyncio.CancelledError:
        try:
            with anyio.CancelScope(shield=True):
                await db.rollback()
                if not provider_started:
                    await refund_llm_reservation(db, user_id, LLM_IMPORT_RESERVE_TOKENS)
        except Exception:
            logger.exception("import cancellation cleanup failed for user=%s", user_id)
        raise
    except Exception:
        logger.exception("import extraction failed for user=%s", user_id)
        try:
            await db.rollback()
            await refund_llm_reservation(db, user_id, LLM_IMPORT_RESERVE_TOKENS)
        except Exception:
            logger.exception("import reservation refund failed for user=%s", user_id)
        raise


async def _persist_provenance_knowledge(
    db: AsyncSession, user_id: int, text: str, source_knowledge_id: int | None
) -> int:
    """Persist or update source note as TaskKnowledge (source_type: NOTE) for provenance."""
    if source_knowledge_id is not None:
        db_knowledge = await knowledge_crud.get_knowledge(db, source_knowledge_id, user_id)
        if not db_knowledge:
            raise HTTPException(status_code=400, detail="Invalid source_knowledge_id")

        needs_reingest = db_knowledge.content != text
        if not needs_reingest:
            existing_chunk = (
                await db.execute(
                    select(KnowledgeChunk.id)
                    .where(
                        KnowledgeChunk.knowledge_id == db_knowledge.id,
                        KnowledgeChunk.user_id == user_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            needs_reingest = existing_chunk is None

        if needs_reingest:
            if db_knowledge.content != text:
                db_knowledge.content = text
                db.add(db_knowledge)
                await db.flush()
            try:
                async with db.begin_nested():
                    await UserKnowledgeIndex().remove_knowledge_chunks(db, user_id, db_knowledge.id)
                    await ingest_knowledge(db, db_knowledge)
                    await UserKnowledgeIndex().ensure_index(db, user_id)
            except Exception as exc:
                logger.warning("knowledge re-ingest failed for id=%s: %s", db_knowledge.id, exc)
        return source_knowledge_id

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Imported Note")
    new_knowledge = TaskKnowledge(
        user_id=user_id,
        task_id=None,
        source_type=SourceType.NOTE,
        title=first_line[:80],
        content=text,
    )
    db.add(new_knowledge)
    await db.flush()
    await db.refresh(new_knowledge)
    try:
        async with db.begin_nested():
            await ingest_knowledge(db, new_knowledge)
            await UserKnowledgeIndex().ensure_index(db, user_id)
    except Exception as exc:
        logger.warning("knowledge ingest failed for id=%s: %s", new_knowledge.id, exc)
    return new_knowledge.id


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

    await _validate_source_knowledge(db, import_in.source_knowledge_id, user_id)

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

    extraction, record, answer_text = await _perform_extraction(db, user_id, import_in.text)

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

    # Provenance: persist source note as TaskKnowledge (source_type: NOTE)
    # so created tasks link back to it and assistant can cite it (audit #93).
    source_knowledge_id = await _persist_provenance_knowledge(
        db, user_id=user_id, text=import_in.text, source_knowledge_id=import_in.source_knowledge_id
    )

    await db.commit()
    return ImportExtractResponse(
        proposals=extraction.proposals,
        reason=extraction.reason,
        source_knowledge_id=source_knowledge_id,
    )
