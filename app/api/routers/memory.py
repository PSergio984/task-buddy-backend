"""API endpoints for the Memory corpus (POST /api/v1/tasks/{task_id}/memory/similar)."""

import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_MEMORY_SIMILAR
from app.crud import knowledge as knowledge_crud
from app.crud import task as task_crud
from app.dependencies import get_db
from app.knowledge.records import LLMCallRecord, citation_text, normalize_citations
from app.knowledge.retrieval import UserKnowledgeIndex
from app.limiter import limiter
from app.models.knowledge import KnowledgeChunk, SourceType, TaskKnowledge
from app.models.user import User
from app.schemas.memory import MemorySimilarResponse, SimilarTaskRow
from app.security import get_confirmed_user

ROUTER_TAG = "memory"
TASK_NOT_FOUND = "Task not found"
TOP_K = 5
SEARCH_LIMIT = 25

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={
        404: {"description": TASK_NOT_FOUND},
        401: {"description": "Not authenticated"},
    },
)

logger = logging.getLogger(__name__)


@router.post(
    "/{task_id}/memory/similar",
    response_model=MemorySimilarResponse,
    responses={404: {"description": TASK_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_MEMORY_SIMILAR)
async def similar_memory_tasks(
    task_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MemorySimilarResponse:
    """Return similar completed tasks to the given task (raw rows, no LLM)."""
    logger.info("POST /tasks/%s/memory/similar - %s", task_id, current_user.id)

    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    query = f"{db_task.title} {db_task.description or ''}".strip()

    start = time.monotonic()
    chunks = await UserKnowledgeIndex().search(db, current_user.id, query, limit=SEARCH_LIMIT)
    response_time = time.monotonic() - start

    deduped: list[dict[str, Any]] = []
    if chunks:
        chunk_ids = [c["chunk_id"] for c in chunks]
        result = await db.execute(
            select(
                KnowledgeChunk.id,
                TaskKnowledge.id,
                TaskKnowledge.title,
                TaskKnowledge.extra_metadata,
                TaskKnowledge.task_id,
            )
            .join(TaskKnowledge, KnowledgeChunk.knowledge_id == TaskKnowledge.id)
            .where(
                KnowledgeChunk.id.in_(chunk_ids),
                TaskKnowledge.source_type == SourceType.HISTORY,
                TaskKnowledge.user_id == current_user.id,
            )
        )
        history_by_chunk: dict[int, tuple[int, str | None, dict | None, int]] = {}
        for row in result.all():
            # (knowledge_id, title, extra_metadata, task_id) keyed by chunk_id
            history_by_chunk[row[0]] = (row[1], row[2], row[3], row[4])

        seen_task_ids: set[int] = set()
        for chunk in chunks:
            joined = history_by_chunk.get(chunk["chunk_id"])
            if joined is None:
                continue  # stale in-memory index entry — drop, never 5xx
            (_knowledge_id, title, extra_metadata, task_id_of_row) = joined
            if task_id_of_row == task_id:
                continue  # exclude the query task itself
            if task_id_of_row in seen_task_ids:
                continue  # task-level dedupe: keep best rrf_score (search order)
            seen_task_ids.add(task_id_of_row)
            deduped.append(
                {
                    "task_id": task_id_of_row,
                    "knowledge_id": _knowledge_id,
                    "title": title or "",
                    "duration_minutes": float(
                        (extra_metadata or {}).get("duration_minutes", 0) or 0
                    ),
                    "rrf_score": chunk["rrf_score"],
                    "chunk_text": citation_text(chunk),
                }
            )
            if len(deduped) >= TOP_K:
                break

    try:
        await knowledge_crud.create_answer(
            db,
            user_id=current_user.id,
            task_id=task_id,
            answer_text="",
            record=LLMCallRecord(
                model="retrieval",
                prompt="",
                instructions="",
                answer="",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                response_time=response_time,
                cost=0,
            ),
            retrieved_chunks=normalize_citations(
                [{**row, "knowledge_id": row["knowledge_id"]} for row in deduped]
            ),
            judge_label=None,
            judge_explanation=None,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning(
            "memory similar instrumentation persist failed for task=%s: %s",
            task_id,
            exc,
        )

    return MemorySimilarResponse(
        task_id=task_id,
        similar_tasks=[
            SimilarTaskRow(
                id=row["task_id"],
                title=row["title"],
                duration_minutes=row["duration_minutes"],
                rrf_score=row["rrf_score"],
                chunk_text=row["chunk_text"],
            )
            for row in deduped
        ],
        response_time_ms=round(response_time * 1000, 2),
    )
