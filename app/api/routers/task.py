from fastapi import APIRouter, HTTPException

from app.api.routers.tasks import task_table, subtask_table
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


# Mock data for demonstration
tbl_task = {
    "1": {
        "id": "1",
        "title": "Learn FastAPI",
        "description": "Study FastAPI framework",
        "completed": False,
    },
    "2": {"id": "2", "title": "Build API", "description": "Create REST API", "completed": False},
}

tbl_subtask = {
    "1": {"id": "1", "task_id": "1", "title": "Read documentation", "completed": False},
    "2": {"id": "2", "task_id": "1", "title": "Watch tutorials", "completed": False},
}


@router.get("/", tags=["tasks"], response_model=list[TaskCreateResponse])
async def get_all_tasks():

    return {"tasks": list(tbl_task.values())}


@router.get("/{task_id}", response_model=TaskCreateResponse)
async def get_task(task: TaskCreateRequest):
    if task.id not in tbl_task:
        raise HTTPException(status_code=404, detail="Task not found")
    return tbl_task.get(task.id)


@router.post("/task", response_model=TaskCreateResponse)
async def create_task(task: TaskCreateRequest):

    new_id = str(len(tbl_task) + 1)
    new_task = {
        "id": new_id,
        "title": task.title,
        "description": task.description,
        "completed": False,
    }
    tbl_task[new_id] = new_task
    return new_task


@router.put("/{task_id}")
async def update_task(
    task_id: str, title: str = None, description: str = None, completed: bool = None
):
    if task_id not in tbl_task:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tbl_task[task_id]
    if title is not None:
        task["title"] = title
    if description is not None:
        task["description"] = description
    if completed is not None:
        task["completed"] = completed

    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    if task_id not in tbl_task:
        raise HTTPException(status_code=404, detail="Task not found")

    deleted_task = tbl_task.pop(task_id)
    return {"message": "Task deleted", "task": deleted_task}


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


@router.post("/subtask", response_model=SubTaskCreateResponse)
async def create_subtask(subtask: SubTaskCreateRequest):
    task = get_task(subtask.task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    data = subtask.dict()
    last_record_id = len(tbl_subtask)
    new_subtask = {**data, "id": last_record_id}
    tbl_subtask[last_record_id] = new_subtask
    return new_subtask


@router.get("/task/{task_id}/subtask", response_model=list[SubTaskCreateResponse])
async def get_subtasks_on_task(task_id: int):
    return [subtask for subtask in tbl_subtask.values() if subtask["task_id"] == task_id]


@router.get("/task/{task_id}/subtask", response_model=list[TaskWithSubTasks])
async def get_task_with_subtasks(task_id: int):
    task = get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"task": task, "subtasks": await get_subtasks_on_task(task_id)}
