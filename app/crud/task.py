from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import selectinload
from app.crud import tag as tag_crud
from app.models.task import SubTask, Task
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
    group_id: Optional[int] = None,
    tag_id: Optional[int] = None,
) -> list[Task]:
    query = select(Task).where(Task.user_id == user_id).options(selectinload(Task.tags))
    if completed is not None:
        query = query.where(Task.completed == completed)
    if group_id is not None:
        query = query.where(Task.group_id == group_id)
    if tag_id is not None:
        query = query.where(Task.tags.any(id=tag_id))
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_task(db: AsyncSession, task_id: int, user_id: int) -> Optional[Task]:
    query = select(Task).where(Task.id == task_id, Task.user_id == user_id).options(selectinload(Task.tags))
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_tasks_by_group(db: AsyncSession, group_id: int, user_id: int) -> list[Task]:
    query = select(Task).where(Task.group_id == group_id, Task.user_id == user_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_task(db: AsyncSession, user_id: int, task_in: TaskCreateRequest) -> Task:
    task_data = task_in.model_dump()
    tag_names = task_data.pop("tags", [])
    
    db_task = Task(
        **task_data,
        user_id=user_id,
    )
    db.add(db_task)
    await db.flush()
    
    # Process tags
    if tag_names:
        for name in tag_names:
            name = name.strip()
            if not name:
                continue
            db_tag = await tag_crud.get_tag_by_name(db, user_id=user_id, name=name)
            if not db_tag:
                db_tag = await tag_crud.create_tag(db, user_id=user_id, tag_in=TagCreate(name=name))
            
            await tag_crud.attach_tag_to_task(db, task_id=db_task.id, tag_id=db_tag.id)
            
    await db.refresh(db_task)
    return db_task


async def update_task(db: AsyncSession, db_task: Task, task_in: TaskUpdateRequest) -> Task:
    update_data = task_in.model_dump(exclude_unset=True)
    tag_names = update_data.pop("tags", None)
    
    for field, value in update_data.items():
        setattr(db_task, field, value)
    db.add(db_task)
    
    if tag_names is not None:
        from app.models.task import task_tags
        stmt = task_tags.delete().where(task_tags.c.task_id == db_task.id)
        await db.execute(stmt)
        
        for name in tag_names:
            name = name.strip()
            if not name:
                continue
            db_tag = await tag_crud.get_tag_by_name(db, user_id=db_task.user_id, name=name)
            if not db_tag:
                db_tag = await tag_crud.create_tag(db, user_id=db_task.user_id, tag_in=TagCreate(name=name))
            
            await tag_crud.attach_tag_to_task(db, task_id=db_task.id, tag_id=db_tag.id)

    await db.flush()
    await db.refresh(db_task)
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
