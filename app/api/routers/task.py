from fastapi import APIRouter, HTTPException

from app.database import database, tbl_task, tbl_subtask
from app.models.task import (
    TaskCreateRequest,
    TaskCreateResponse,
    SubTaskCreateRequest,
    SubTaskCreateResponse,
    TaskWithSubTasks,
)

router = APIRouter(
    tags=["tasks"],
    responses={404: {"description": "Task not found"}},
)


@router.get("/task", tags=["tasks"], response_model=list[TaskCreateResponse])
async def get_all_tasks():
    query = tbl_task.select()
    return await database.fetch_all(query)


@router.get("/task/{task_id}", response_model=TaskCreateResponse)
async def get_task(task_id: int):
    query = tbl_task.select().where(tbl_task.c.id == task_id)
    return await database.fetch_one(query)


@router.post("/task", response_model=TaskCreateResponse, status_code=201)
async def create_task(task: TaskCreateRequest):
    data = task.model_dump()
    query = tbl_task.insert().values(**data)
    last_record_id = await database.execute(query)
    return {**data, "id": last_record_id}


@router.put("/{task_id}")
async def update_task(
    task_id: str, title: str = None, description: str = None, completed: bool = None
):
    if task_id not in tbl_task:
        raise HTTPException(status_code=404, detail="Task not found")

    query = tbl_task.update().where(tbl_task.c.id == task_id)
    update_data = {}
    if title is not None:
        update_data["title"] = title
    if description is not None:
        update_data["description"] = description
    if completed is not None:
        update_data["completed"] = completed
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    await database.execute(query.values(**update_data))
    return {"message": "Task updated successfully"}


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    if task_id not in tbl_task:
        raise HTTPException(status_code=404, detail="Task not found")

    query = tbl_task.delete().where(tbl_task.c.id == task_id)
    await database.execute(query)
    return {"message": "Task deleted successfully"}


@router.get("/{task_id}/subtasks", response_model=SubTaskCreateResponse)
async def get_subtasks(subtask: SubTaskCreateRequest):
    if SubTaskCreateRequest.task_id not in tbl_task:
        raise HTTPException(status_code=404, detail="Task not found")

    subtasks = [
        subtask
        for subtask in tbl_subtask.values()
        if subtask["task_id"] == SubTaskCreateRequest.task_id
    ]
    return {"subtasks": subtasks}


@router.post("/subtask", response_model=SubTaskCreateResponse, status_code=201)
async def create_subtask(subtask: SubTaskCreateRequest):
    task = await get_task(subtask.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    data = subtask.model_dump()
    query = tbl_subtask.insert().values(**data)
    last_record_id = await database.execute(query)
    return {**data, "id": last_record_id}


@router.get("/task/{task_id}/subtask", response_model=list[SubTaskCreateResponse])
async def get_subtasks_on_task(task_id: int):

    query = tbl_subtask.select().where(tbl_subtask.c.task_id == task_id)
    return await database.fetch_all(query)


@router.get("/task/{task_id}/subtask", response_model=list[TaskWithSubTasks])
async def get_task_with_subtasks(task_id: int):
    task = await get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"task": task, "subtasks": await get_subtasks_on_task(task_id)}
