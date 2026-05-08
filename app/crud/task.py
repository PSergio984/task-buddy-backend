from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import SubTask, Task
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
    group_id: Optional[int] = None,
) -> list[Task]:
    query = select(Task).where(Task.user_id == user_id)
    if completed is not None:
        query = query.where(Task.completed == completed)
    if group_id is not None:
        query = query.where(Task.group_id == group_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_task(db: AsyncSession, task_id: int, user_id: int) -> Optional[Task]:
    query = select(Task).where(Task.id == task_id, Task.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_tasks_by_group(db: AsyncSession, group_id: int, user_id: int) -> list[Task]:
    query = select(Task).where(Task.group_id == group_id, Task.user_id == user_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_task(db: AsyncSession, user_id: int, task_in: TaskCreateRequest) -> Task:
    db_task = Task(
        **task_in.model_dump(),
        user_id=user_id,
    )
    db.add(db_task)
    await db.flush()
    # No commit here as per design
    return db_task


async def update_task(db: AsyncSession, db_task: Task, task_in: TaskUpdateRequest) -> Task:
    update_data = task_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_task, field, value)
    db.add(db_task)
    await db.flush()
    return db_task


async def delete_task(db: AsyncSession, db_task: Task) -> None:
    await db.delete(db_task)


# SubTask CRUD
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


async def update_subtask(db: AsyncSession, db_subtask: SubTask, subtask_in: SubTaskUpdateRequest) -> SubTask:
    update_data = subtask_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_subtask, field, value)
    db.add(db_subtask)
    await db.flush()
    return db_subtask


async def delete_subtask(db: AsyncSession, db_subtask: SubTask) -> None:
    await db.delete(db_subtask)


async def get_subtasks_on_task(db: AsyncSession, task_id: int) -> list[SubTask]:
    query = select(SubTask).where(SubTask.task_id == task_id)
    result = await db.execute(query)
    return list(result.scalars().all())
