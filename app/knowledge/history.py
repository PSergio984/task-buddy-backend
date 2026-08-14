"""History corpus orchestration: row-build helpers for completed-task memory.

Completed tasks become TaskKnowledge rows (source_type=HISTORY) whose content
is the task's title + description; duration is derived from timestamps at
ingest time (D-02/D-03) and stored in the row's extra_metadata.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.knowledge import get_history_knowledge_for_task
from app.knowledge.ingest import ingest_knowledge
from app.knowledge.retrieval import UserKnowledgeIndex
from app.models.knowledge import SourceType, TaskKnowledge
from app.models.task import Task

logger = logging.getLogger(__name__)


def compute_duration_minutes(created_at: datetime, updated_at: datetime) -> float:
    """Minutes between creation and the ingest-time update (D-02/D-03).

    Negative values (clock skew) clamp to 0.0.
    """
    return max(0.0, round((updated_at - created_at).total_seconds() / 60, 2))


def build_history_content(title: str, description: str | None) -> str:
    """The indexed document text: title + description joined as plain text."""
    if description:
        return f"{title}\n{description}".strip()
    return title


async def create_history_knowledge(db: AsyncSession, task: Task) -> Optional[TaskKnowledge]:
    """Build and ingest a completed task's history row (D-07 guard first).

    Flush-not-commit (repo convention): the caller owns the transaction.
    Returns None when a history row already exists for the task (dedupe) or
    when ingest fails (whole operation rolls back — a row without chunks would
    be a silent retrieval gap; the startup sweep self-heals, D-06).
    """
    if await get_history_knowledge_for_task(db, task.id, task.user_id):
        return None
    row = TaskKnowledge(
        user_id=task.user_id,
        task_id=task.id,
        source_type=SourceType.HISTORY,
        title=task.title,
        content=build_history_content(task.title, task.description),
        extra_metadata={
            "duration_minutes": compute_duration_minutes(task.created_at, task.updated_at)
        },
    )
    db.add(row)
    await db.flush()
    try:
        await ingest_knowledge(db, row)
    except Exception as exc:
        await db.rollback()
        logger.warning("history ingest failed for task=%s: %s", task.id, exc)
        return None
    return row


async def delete_history_knowledge(db: AsyncSession, task_id: int, user_id: int) -> bool:
    """Remove a task's history row and its chunks (flush-not-commit)."""
    row = await get_history_knowledge_for_task(db, task_id, user_id)
    if not row:
        return False
    await UserKnowledgeIndex().remove_knowledge_chunks(db, user_id, row.id)
    await db.delete(row)
    return True


async def ingest_history_task(task_id: int, user_id: int) -> None:
    """Fire-and-forget history ingest for a just-completed task (D-05).

    Opens its own session because the request-scoped session is not safe for
    the slow lazy embedder; re-fetches the task scoped by user_id so the
    callable can never read another user's task.
    """
    from app.crud import task as task_crud
    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            task = await task_crud.get_task(session, task_id=task_id, user_id=user_id)
            if task and task.completed:
                # Re-check completed: an un-complete landing between the hook
                # and this callable's execution must not create a stale row
                # (D-11 corpus purity). The D-07 guard would otherwise swallow
                # a later re-complete.
                row = await create_history_knowledge(session, task)
                if row is not None:
                    await session.commit()
    except Exception:
        logger.exception(
            "history ingest background task failed for task=%s user=%s",
            task_id,
            user_id,
        )


async def backfill_history_corpus(db: AsyncSession) -> int:
    """Ingest every completed task lacking a history row (D-06, idempotent)."""
    result = await db.execute(select(Task).where(Task.completed.is_(True)).order_by(Task.id))
    tasks = result.scalars().all()
    count = 0
    for task in tasks:
        if await get_history_knowledge_for_task(db, task.id, task.user_id):
            continue
        row = await create_history_knowledge(db, task)
        if row is not None:
            # Per-task commit: one failing task rolls back only itself
            # (create_history_knowledge) and never the sweep's earlier wins.
            await db.commit()
            count += 1
    logger.info("history backfill: %s/%s tasks ingested", count, len(tasks))
    return count


async def history_backfill_sweep() -> None:
    """Detached startup sweep with its own session (D-06)."""
    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            await backfill_history_corpus(session)
    except Exception:
        logger.exception("history backfill sweep failed")
