from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud import tag as tag_crud
from app.libs.audit import audit_log
from app.models.task import SubTask, Task, task_tags
from app.schemas.enums import AuditAction
from app.schemas.tag import TagCreate
from app.schemas.task import (
    SubTaskCreateRequest,
    SubTaskUpdateRequest,
    TaskCreateRequest,
    TaskUpdateRequest,
)


async def get_tasks(
    db: AsyncSession,
    user_id: int,
    completed: Optional[bool] = None,
    project_id: Optional[int] = None,
    tag_id: Optional[int] = None,
) -> list[Task]:
    query = select(Task).where(Task.user_id == user_id).options(
        selectinload(Task.tags),
        selectinload(Task.subtasks)
    )
    if completed is not None:
        query = query.where(Task.completed == completed)
    if project_id is not None:
        query = query.where(Task.project_id == project_id)
    if tag_id is not None:
        query = query.where(Task.tags.any(id=tag_id))
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_task(db: AsyncSession, task_id: int, user_id: int) -> Optional[Task]:
    query = select(Task).where(Task.id == task_id, Task.user_id == user_id).options(
        selectinload(Task.tags),
        selectinload(Task.subtasks)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_tasks_by_project(db: AsyncSession, project_id: int, user_id: int) -> list[Task]:
    query = (
        select(Task)
        .where(Task.project_id == project_id, Task.user_id == user_id)
        .options(
            selectinload(Task.tags),
            selectinload(Task.subtasks)
        )
    )
    result = await db.execute(query)
    return list(result.scalars().all())


@audit_log(action=AuditAction.CREATE, target_type="TASK")
async def create_task(db: AsyncSession, user_id: int, task_in: TaskCreateRequest) -> Task:
    task_data = task_in.model_dump()
    tag_names = task_data.pop("tags", [])
    subtasks_data = task_data.pop("subtasks", [])

    db_task = Task(
        **task_data,
        user_id=user_id,
    )
    db.add(db_task)
    await db.flush()

    # Process tags (normalized and deduped)
    if tag_names:
        unique_tags = list(dict.fromkeys(name.strip() for name in tag_names if name.strip()))
        for name in unique_tags:
            db_tag = await tag_crud.get_tag_by_name(db, user_id=user_id, name=name)
            if not db_tag:
                db_tag = await tag_crud.create_tag(db, user_id=user_id, tag_in=TagCreate(name=name))

            await tag_crud.attach_tag_to_task(db, task_id=db_task.id, tag_id=db_tag.id, user_id=user_id)

    # Process nested subtasks
    if subtasks_data:
        for st_data in subtasks_data:
            db_subtask = SubTask(
                **st_data,
                task_id=db_task.id,
                user_id=user_id
            )
            db.add(db_subtask)

    await db.flush()
    await db.refresh(db_task)
    return db_task


@audit_log(action=AuditAction.UPDATE, target_type="TASK", include_diff=True)
async def update_task(db: AsyncSession, db_task: Task, task_in: TaskUpdateRequest) -> Task:
    update_data = task_in.model_dump(exclude_unset=True)
    tag_names = update_data.pop("tags", None)

    for field, value in update_data.items():
        setattr(db_task, field, value)
    db.add(db_task)

    if tag_names is not None:
        stmt = task_tags.delete().where(task_tags.c.task_id == db_task.id)
        await db.execute(stmt)

        unique_tags = list(dict.fromkeys(name.strip() for name in tag_names if name.strip()))
        for name in unique_tags:
            db_tag = await tag_crud.get_tag_by_name(db, user_id=db_task.user_id, name=name)
            if not db_tag:
                db_tag = await tag_crud.create_tag(db, user_id=db_task.user_id, tag_in=TagCreate(name=name))

            await tag_crud.attach_tag_to_task(db, task_id=db_task.id, tag_id=db_tag.id, user_id=db_task.user_id)

    await db.flush()
    await db.refresh(db_task)
    return db_task


@audit_log(action=AuditAction.DELETE, target_type="TASK")
async def delete_task(db: AsyncSession, db_task: Task) -> None:
    await db.delete(db_task)


# SubTask CRUD
@audit_log(action=AuditAction.CREATE, target_type="SUBTASK")
async def create_subtask(db: AsyncSession, task_id: int, user_id: int, subtask_in: SubTaskCreateRequest) -> SubTask:
    subtask_data = subtask_in.model_dump()
    subtask_data.pop("task_id", None)  # Avoid duplicate task_id
    db_subtask = SubTask(
        **subtask_data,
        task_id=task_id,
        user_id=user_id
    )
    db.add(db_subtask)
    await db.flush()
    return db_subtask


async def get_subtask(db: AsyncSession, subtask_id: int, user_id: int) -> Optional[SubTask]:
    query = select(SubTask).where(SubTask.id == subtask_id, SubTask.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


@audit_log(action=AuditAction.UPDATE, target_type="SUBTASK", include_diff=True)
async def update_subtask(db: AsyncSession, db_subtask: SubTask, subtask_in: SubTaskUpdateRequest) -> SubTask:
    update_data = subtask_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_subtask, field, value)
    db.add(db_subtask)
    await db.flush()
    return db_subtask


@audit_log(action=AuditAction.DELETE, target_type="SUBTASK")
async def delete_subtask(db: AsyncSession, db_subtask: SubTask) -> None:
    await db.delete(db_subtask)


async def get_subtasks_on_task(db: AsyncSession, task_id: int) -> list[SubTask]:
    query = select(SubTask).where(SubTask.task_id == task_id)
    result = await db.execute(query)
    return list(result.scalars().all())
