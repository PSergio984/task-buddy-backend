import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.database import database, tbl_subtask, tbl_task
from app.models.task import (
    SubTaskCreateRequest,
    SubTaskCreateResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskWithSubTasks,
)

router = APIRouter(
    tags=["tasks"],
    responses={404: {"description": "Task not found"}},
)

logger = logging.getLogger(__name__)


@router.get("/", tags=["tasks"], response_model=list[TaskCreateResponse])
async def get_all_tasks():
    logger.info("GET / - fetching tasks")
    query = tbl_task.select()
    tasks = await database.fetch_all(query)
    logger.info("GET / - fetched %s tasks", len(tasks))
    return tasks


@router.get("/{task_id}", response_model=TaskCreateResponse)
async def get_task(task_id: int):
    logger.info("GET /%s - fetching task", task_id)
    query = tbl_task.select().where(tbl_task.c.id == task_id)
    task = await database.fetch_one(query)

    if not task:
        logger.warning("GET /%s - task not found", task_id)
        raise HTTPException(status_code=404, detail="Task not found")

    logger.info("GET /%s - task found", task_id)
    return task


@router.post("/", response_model=TaskCreateResponse, status_code=201)
async def create_task(task: TaskCreateRequest):
    logger.info("POST / - creating task title=%s", task.title)
    data = task.model_dump()
    data["created_at"] = datetime.now()
    query = tbl_task.insert().values(**data)
    last_record_id = await database.execute(query)
    logger.info("POST / - created task id=%s", last_record_id)
    return {**data, "id": last_record_id}


@router.put("/{task_id}")
async def update_task(
    task_id: int, title: str = None, description: str = None, completed: bool = None
):
    logger.info("PUT /%s - updating task", task_id)
    existing_task = await database.fetch_one(tbl_task.select().where(tbl_task.c.id == task_id))

    if not existing_task:
        logger.warning("PUT /%s - task not found", task_id)
        raise HTTPException(status_code=404, detail="Task not found")

    update_data = {}
    if title is not None:
        update_data["title"] = title
    if description is not None:
        update_data["description"] = description
    if completed is not None:
        update_data["completed"] = completed

    if not update_data:
        logger.warning("PUT /%s - no fields to update", task_id)
        raise HTTPException(status_code=400, detail="No fields to update")

    query = tbl_task.update().where(tbl_task.c.id == task_id)
    await database.execute(query.values(**update_data))
    logger.info("PUT /%s - task updated", task_id)
    return {"message": "Task updated successfully"}


@router.delete("/{task_id}")
async def delete_task(task_id: int):
    logger.info("DELETE /%s - deleting task", task_id)
    existing_task = await database.fetch_one(tbl_task.select().where(tbl_task.c.id == task_id))

    if not existing_task:
        logger.warning("DELETE /%s - task not found", task_id)
        raise HTTPException(status_code=404, detail="Task not found")

    query = tbl_task.delete().where(tbl_task.c.id == task_id)
    await database.execute(query)
    logger.info("DELETE /%s - task deleted", task_id)
    return {"message": "Task deleted successfully"}


@router.get("/{task_id}/subtasks", response_model=TaskWithSubTasks)
async def get_task_with_subtasks(task_id: int):
    logger.info("GET /%s/subtasks - fetching task and subtasks", task_id)
    task = await get_task(task_id)
    subtasks = await get_subtasks_on_task(task_id)
    logger.info("GET /%s/subtasks - fetched %s subtasks", task_id, len(subtasks))
    return {"task": task, "subtasks": subtasks}


@router.post("/subtask", response_model=SubTaskCreateResponse, status_code=201)
async def create_subtask(subtask: SubTaskCreateRequest):
    logger.info("POST /subtask - creating subtask for task_id=%s", subtask.task_id)
    await get_task(subtask.task_id)

    data = subtask.model_dump()
    data["created_at"] = datetime.now()
    query = tbl_subtask.insert().values(**data)
    last_record_id = await database.execute(query)
    logger.info("POST /subtask - created subtask id=%s", last_record_id)
    return {**data, "id": last_record_id}


@router.get("/{task_id}/subtask", response_model=list[SubTaskCreateResponse])
async def get_subtasks_on_task(task_id: int):
    logger.info("GET /%s/subtask - fetching subtasks", task_id)
    await get_task(task_id)  # Validates task exists, raises 404 if not
    query = tbl_subtask.select().where(tbl_subtask.c.task_id == task_id)
    subtasks = await database.fetch_all(query)
    logger.info("GET /%s/subtask - fetched %s subtasks", task_id, len(subtasks))
    return subtasks
