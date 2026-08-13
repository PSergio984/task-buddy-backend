"""CRUD operations for task-attached knowledge."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.libs.audit import audit_log
from app.models.knowledge import TaskKnowledge
from app.schemas.enums import AuditAction
from app.schemas.knowledge import KnowledgeCreateRequest, KnowledgeUpdateRequest


async def get_knowledge(
    db: AsyncSession, knowledge_id: int, user_id: int
) -> Optional[TaskKnowledge]:
    query = select(TaskKnowledge).where(
        TaskKnowledge.id == knowledge_id, TaskKnowledge.user_id == user_id
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def list_knowledge_for_task(
    db: AsyncSession, task_id: int, user_id: int, skip: int = 0, limit: int = 50
) -> list[TaskKnowledge]:
    query = (
        select(TaskKnowledge)
        .where(TaskKnowledge.task_id == task_id, TaskKnowledge.user_id == user_id)
        .order_by(TaskKnowledge.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


@audit_log(action=AuditAction.CREATE, target_type="KNOWLEDGE")
async def create_knowledge(
    db: AsyncSession, task_id: int, user_id: int, knowledge_in: KnowledgeCreateRequest
) -> TaskKnowledge:
    knowledge_data = knowledge_in.model_dump(exclude_none=True)
    # Wire "metadata" maps to the ORM attribute extra_metadata (H1).
    knowledge_data["extra_metadata"] = knowledge_data.pop("metadata_", {})
    db_knowledge = TaskKnowledge(**knowledge_data, task_id=task_id, user_id=user_id)
    db.add(db_knowledge)
    await db.flush()
    await db.refresh(db_knowledge)
    return db_knowledge


@audit_log(action=AuditAction.UPDATE, target_type="KNOWLEDGE", include_diff=True)
async def update_knowledge(
    db: AsyncSession, knowledge_id: int, user_id: int, knowledge_in: KnowledgeUpdateRequest
) -> Optional[TaskKnowledge]:
    db_knowledge = await get_knowledge(db, knowledge_id, user_id)
    if not db_knowledge:
        return None

    update_data = knowledge_in.model_dump(exclude_unset=True)
    if "metadata_" in update_data:
        update_data["extra_metadata"] = update_data.pop("metadata_")

    for field, value in update_data.items():
        if field == "content" and value is None:
            continue
        if field == "extra_metadata" and value is None:
            db_knowledge.extra_metadata = {}
            continue
        setattr(db_knowledge, field, value)
    db.add(db_knowledge)
    await db.flush()
    await db.refresh(db_knowledge)
    return db_knowledge


@audit_log(action=AuditAction.DELETE, target_type="KNOWLEDGE")
async def delete_knowledge(db: AsyncSession, knowledge_id: int, user_id: int) -> bool:
    db_knowledge = await get_knowledge(db, knowledge_id, user_id)
    if not db_knowledge:
        return False
    await db.delete(db_knowledge)
    return True
