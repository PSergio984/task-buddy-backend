from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.task import Task, SubTask
from app.schemas.task import TaskCreateRequest, TaskUpdateRequest, SubTaskCreateRequest, SubTaskUpdateRequest


async def get_tasks(db: AsyncSession, user_id: int, completed: Optional[bool] = None) -> List[Task]:
    query = select(Task).where(Task.user_id == user_id)
    if completed is not None:
        query = query.where(Task.completed == completed)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_task(db: AsyncSession, task_id: int, user_id: int) -> Optional[Task]:
    query = select(Task).where(Task.id == task_id, Task.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_task(db: AsyncSession, user_id: int, task_in: TaskCreateRequest) -> Task:
    db_task = Task(
        **task_in.model_dump(),
        user_id=user_id,
    )
    db.add(db_task)
    # No commit here as per design
    return db_task


async def update_task(db: AsyncSession, db_task: Task, task_in: TaskUpdateRequest) -> Task:
    update_data = task_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_task, field, value)
    db.add(db_task)
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
    return db_subtask


async def delete_subtask(db: AsyncSession, db_subtask: SubTask) -> None:
    await db.delete(db_subtask)


async def get_subtasks_on_task(db: AsyncSession, task_id: int) -> List[SubTask]:
    query = select(SubTask).where(SubTask.task_id == task_id)
    result = await db.execute(query)
    return list(result.scalars().all())
