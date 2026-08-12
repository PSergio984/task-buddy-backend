"""API endpoints for task-attached knowledge (notes)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.task import invalidate_task_cache
from app.config import (
    RATE_LIMIT_KNOWLEDGE_CREATE,
    RATE_LIMIT_KNOWLEDGE_DELETE,
    RATE_LIMIT_KNOWLEDGE_LIST,
    RATE_LIMIT_KNOWLEDGE_UPDATE,
)
from app.crud import knowledge as knowledge_crud
from app.crud import task as task_crud
from app.dependencies import get_db
from app.knowledge.ingest import ingest_knowledge
from app.knowledge.retrieval import UserKnowledgeIndex
from app.limiter import limiter
from app.models.knowledge import SourceType, TaskKnowledge
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeCreateRequest,
    KnowledgeResponse,
    KnowledgeUpdateRequest,
)
from app.security import get_confirmed_user

# Constants to avoid duplicated string literals
ROUTER_TAG = "knowledge"
TASK_NOT_FOUND = "Task not found"
KNOWLEDGE_NOT_FOUND = "Knowledge not found"
NO_FIELDS_TO_UPDATE = "No fields to update"

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
    responses={404: {"description": TASK_NOT_FOUND}},
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
    responses={404: {"description": KNOWLEDGE_NOT_FOUND}},
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
    # Drop the deleted chunks from the in-memory index.
    await UserKnowledgeIndex().ensure_index(db, current_user.id)

    logger.info("DELETE /tasks/%s/knowledge/%s - deleted", task_id, knowledge_id)
    await invalidate_task_cache(current_user.id, task_id)
    response.status_code = 204
    return response
