"""API endpoints for task-attached knowledge (notes)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.task import invalidate_task_cache
from app.config import (
    RATE_LIMIT_KNOWLEDGE_ASK,
    RATE_LIMIT_KNOWLEDGE_CREATE,
    RATE_LIMIT_KNOWLEDGE_DELETE,
    RATE_LIMIT_KNOWLEDGE_FEEDBACK,
    RATE_LIMIT_KNOWLEDGE_LIST,
    RATE_LIMIT_KNOWLEDGE_UPDATE,
)
from app.crud import knowledge as knowledge_crud
from app.crud import task as task_crud
from app.dependencies import get_db
from app.knowledge.assistant import KnowledgeAssistant
from app.knowledge.ingest import ingest_knowledge
from app.knowledge.retrieval import UserKnowledgeIndex
from app.limiter import limiter
from app.models.knowledge import KnowledgeFeedback, SourceType, TaskKnowledge
from app.models.user import User
from app.schemas.knowledge import (
    Citation,
    FeedbackCreateRequest,
    FeedbackResponse,
    KnowledgeAskRequest,
    KnowledgeAskResponse,
    KnowledgeCreateRequest,
    KnowledgeResponse,
    KnowledgeUpdateRequest,
)
from app.security import get_confirmed_user

# Constants to avoid duplicated string literals
ROUTER_TAG = "knowledge"
TASK_NOT_FOUND = "Task not found"
KNOWLEDGE_NOT_FOUND = "Knowledge not found"
ANSWER_NOT_FOUND = "Answer not found"
NO_FIELDS_TO_UPDATE = "No fields to update"
AI_NOT_CONFIGURED = "AI assistant not configured"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={
        404: {"description": TASK_NOT_FOUND},
        401: {"description": "Not authenticated"},
    },
)

logger = logging.getLogger(__name__)


@router.post(
    "/{task_id}/knowledge",
    response_model=KnowledgeResponse,
    status_code=201,
    responses={
        404: {"description": TASK_NOT_FOUND},
        400: {"description": "Bad request"},
    },
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_CREATE)
async def create_knowledge(
    task_id: int,
    knowledge_in: KnowledgeCreateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskKnowledge:
    logger.info("POST /tasks/%s/knowledge - %s", task_id, current_user.id)

    if knowledge_in.source_type != SourceType.NOTE:
        raise HTTPException(
            status_code=400, detail="Only the note source type is supported for now"
        )

    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    db_knowledge: TaskKnowledge = await knowledge_crud.create_knowledge(
        db, task_id=task_id, user_id=current_user.id, knowledge_in=knowledge_in
    )
    await db.commit()
    await db.refresh(db_knowledge)

    # Index the note for retrieval (chunks persisted in a second transaction).
    # Ingest failure degrades search only — the note itself stays saved.
    try:
        await ingest_knowledge(db, db_knowledge)
        await db.commit()
        await UserKnowledgeIndex().ensure_index(db, current_user.id)
    except Exception as exc:
        await db.rollback()
        logger.warning("knowledge ingest failed for id=%s: %s", db_knowledge.id, exc)

    logger.info("POST /tasks/%s/knowledge - created id=%s", task_id, db_knowledge.id)
    await invalidate_task_cache(current_user.id, task_id)
    return db_knowledge


@router.get(
    "/{task_id}/knowledge",
    response_model=list[KnowledgeResponse],
    responses={404: {"description": TASK_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_LIST)
async def list_knowledge(
    task_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TaskKnowledge]:
    logger.info("GET /tasks/%s/knowledge - %s", task_id, current_user.id)

    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    return await knowledge_crud.list_knowledge_for_task(
        db, task_id=task_id, user_id=current_user.id, skip=offset, limit=limit
    )


@router.get(
    "/{task_id}/knowledge/{knowledge_id}",
    response_model=KnowledgeResponse,
    responses={404: {"description": KNOWLEDGE_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_LIST)
async def get_knowledge(
    task_id: int,
    knowledge_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskKnowledge:
    logger.info("GET /tasks/%s/knowledge/%s - %s", task_id, knowledge_id, current_user.id)

    db_knowledge = await knowledge_crud.get_knowledge(
        db, knowledge_id=knowledge_id, user_id=current_user.id
    )
    if not db_knowledge or db_knowledge.task_id != task_id:
        raise HTTPException(status_code=404, detail=KNOWLEDGE_NOT_FOUND)

    return db_knowledge


@router.put(
    "/{task_id}/knowledge/{knowledge_id}",
    response_model=KnowledgeResponse,
    responses={
        404: {"description": KNOWLEDGE_NOT_FOUND},
        400: {"description": "Bad request"},
    },
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_UPDATE)
async def update_knowledge(
    task_id: int,
    knowledge_id: int,
    knowledge_update: KnowledgeUpdateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskKnowledge:
    logger.info("PUT /tasks/%s/knowledge/%s - %s", task_id, knowledge_id, current_user.id)

    update_data = knowledge_update.model_dump(exclude_unset=True)
    if not update_data:
        logger.warning("PUT /tasks/%s/knowledge/%s - no fields to update", task_id, knowledge_id)
        raise HTTPException(status_code=400, detail=NO_FIELDS_TO_UPDATE)

    db_knowledge: TaskKnowledge | None = await knowledge_crud.update_knowledge(
        db, knowledge_id=knowledge_id, user_id=current_user.id, knowledge_in=knowledge_update
    )
    if not db_knowledge or db_knowledge.task_id != task_id:
        raise HTTPException(status_code=404, detail=KNOWLEDGE_NOT_FOUND)

    await db.commit()
    await db.refresh(db_knowledge)

    # Re-index: drop the old chunks, embed the updated content.
    # Failure degrades search only — the content edit itself stays saved.
    try:
        await UserKnowledgeIndex().remove_knowledge_chunks(
            db, user_id=current_user.id, knowledge_id=db_knowledge.id
        )
        await ingest_knowledge(db, db_knowledge)
        await db.commit()
        await UserKnowledgeIndex().ensure_index(db, current_user.id)
    except Exception as exc:
        await db.rollback()
        logger.warning("knowledge re-ingest failed for id=%s: %s", db_knowledge.id, exc)

    logger.info("PUT /tasks/%s/knowledge/%s - updated", task_id, knowledge_id)
    await invalidate_task_cache(current_user.id, task_id)
    return db_knowledge


@router.delete(
    "/{task_id}/knowledge/{knowledge_id}",
    status_code=204,
    responses={404: {"description": KNOWLEDGE_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_DELETE)
async def delete_knowledge(
    task_id: int,
    knowledge_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    logger.info("DELETE /tasks/%s/knowledge/%s - %s", task_id, knowledge_id, current_user.id)

    db_knowledge = await knowledge_crud.get_knowledge(
        db, knowledge_id=knowledge_id, user_id=current_user.id
    )
    if not db_knowledge or db_knowledge.task_id != task_id:
        raise HTTPException(status_code=404, detail=KNOWLEDGE_NOT_FOUND)

    deleted = await knowledge_crud.delete_knowledge(
        db, knowledge_id=knowledge_id, user_id=current_user.id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail=KNOWLEDGE_NOT_FOUND)

    await UserKnowledgeIndex().remove_knowledge_chunks(
        db, user_id=current_user.id, knowledge_id=knowledge_id
    )
    await db.commit()
    try:
        # Drop the deleted chunks from the in-memory index. A rebuild failure
        # must not 5xx an already-committed deletion.
        await UserKnowledgeIndex().ensure_index(db, current_user.id)
    except Exception as exc:
        logger.warning("knowledge index rebuild failed after delete id=%s: %s", knowledge_id, exc)

    logger.info("DELETE /tasks/%s/knowledge/%s - deleted", task_id, knowledge_id)
    await invalidate_task_cache(current_user.id, task_id)
    response.status_code = 204
    return response


@router.post(
    "/{task_id}/knowledge/ask",
    response_model=KnowledgeAskResponse,
    responses={
        404: {"description": TASK_NOT_FOUND},
        503: {"description": AI_NOT_CONFIGURED},
    },
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_ASK)
async def ask_knowledge(
    task_id: int,
    ask_in: KnowledgeAskRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeAskResponse:
    """Answer 'what do I need for this task' from the task's knowledge.

    Ownership runs BEFORE any LLM call (T-7-14: a foreign task 404s with zero
    spend). The OpenAI key check lives in ``_openai_client``; a missing key
    surfaces as a generic 503 (no key-presence leak, T-7-13).
    """
    logger.info("POST /tasks/%s/knowledge/ask - %s", task_id, current_user.id)

    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    assistant = KnowledgeAssistant()
    try:
        answer_row = await assistant.ask(db, db_task, ask_in.query)
    except RuntimeError as exc:
        logger.warning("knowledge ask unavailable for task=%s: %s", task_id, exc)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc

    await db.commit()
    await db.refresh(answer_row)

    citations = [Citation.model_validate(chunk) for chunk in (answer_row.retrieved_chunks or [])]
    logger.info(
        "POST /tasks/%s/knowledge/ask - answered id=%s model=%s",
        task_id,
        answer_row.id,
        answer_row.model,
    )
    return KnowledgeAskResponse(
        task_id=task_id,
        answer=answer_row.answer,
        citations=citations,
        model=answer_row.model,
        prompt_tokens=answer_row.prompt_tokens,
        completion_tokens=answer_row.completion_tokens,
        total_tokens=answer_row.total_tokens,
        cost_usd=float(answer_row.cost_usd or 0),
        response_time_ms=answer_row.response_time_ms,
        judge_verdict=answer_row.judge_verdict.value if answer_row.judge_verdict else None,
        judge_explanation=answer_row.judge_explanation,
        answer_id=answer_row.id,
    )


@router.post(
    "/{task_id}/knowledge/answers/{answer_id}/feedback",
    response_model=FeedbackResponse,
    status_code=201,
    responses={404: {"description": ANSWER_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_FEEDBACK)
async def create_answer_feedback(
    task_id: int,
    answer_id: int,
    feedback_in: FeedbackCreateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeFeedback:
    """Record user +1/-1 feedback on an answer (owner-only, T-7-15/T-7-16)."""
    logger.info(
        "POST /tasks/%s/knowledge/answers/%s/feedback - %s",
        task_id,
        answer_id,
        current_user.id,
    )

    db_answer = await knowledge_crud.get_answer(db, answer_id=answer_id, user_id=current_user.id)
    if not db_answer or db_answer.task_id != task_id:
        raise HTTPException(status_code=404, detail=ANSWER_NOT_FOUND)

    feedback_row = await knowledge_crud.create_feedback(
        db,
        user_id=current_user.id,
        answer_id=answer_id,
        rating=feedback_in.rating,
        comment=feedback_in.comment,
    )
    await db.commit()
    await db.refresh(feedback_row)
    return feedback_row
