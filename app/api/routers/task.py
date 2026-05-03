import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.database import database, tbl_subtask, tbl_task, tbl_tag, tbl_task_tags
from app.models.task import (
    SubTaskCreateRequest,
    SubTaskCreateResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskWithSubTasks,
)
from app.models.tag import TagResponse, TagCreate

from app.models.user import User
from app.security import get_current_user

# Constants to avoid duplicated string literals
ROUTER_TAG = "tasks"
TASK_NOT_FOUND = "Task not found"
BAD_REQUEST = "Bad request"
NO_FIELDS_TO_UPDATE = "No fields to update"
NOT_AUTHORIZED_MODIFY_TASK = "Not authorized to modify this task"
NOT_AUTHORIZED_VIEW_TAGS = "Not authorized to view this task's tags"
SUBTASK_PATH = "/subtask"
SUBTASKS_PATH = "/{task_id}/subtasks"
TASK_SUBTASK_PATH = "/{task_id}/subtask"
TAGS_PATH = "/{task_id}/tags"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={404: {"description": TASK_NOT_FOUND}},
)

logger = logging.getLogger(__name__)


# Centralize task ownership checks so endpoints stay consistent.
def ensure_task_owner(task, current_user: User, detail: str) -> None:
    if task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail=detail)


# Return 201 when a task-tag link is created, otherwise 200 for idempotent attach.
def set_tag_link_response_status(response: Response, link_created: bool) -> None:
    response.status_code = 201 if link_created else 200


@router.get("/", response_model=list[TaskCreateResponse])
async def get_all_tasks():
    logger.info("GET / - fetching tasks")
    query = tbl_task.select()
    tasks = await database.fetch_all(query)
    logger.info("GET / - fetched %s tasks", len(tasks))
    return tasks


@router.get(
    "/{task_id}",
    response_model=TaskCreateResponse,
    responses={404: {"description": TASK_NOT_FOUND}},
)
async def get_task(task_id: int):
    logger.info("GET /%s - fetching task", task_id)
    query = tbl_task.select().where(tbl_task.c.id == task_id)
    task = await database.fetch_one(query)

    if not task:
        logger.warning("GET /%s - task not found", task_id)
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    logger.info("GET /%s - task found", task_id)
    return task


@router.post("/", response_model=TaskCreateResponse, status_code=201)
async def create_task(
    task: TaskCreateRequest, current_user: Annotated[User, Depends(get_current_user)]
):
    logger.info("POST / - creating task title=%s", task.title)

    data = task.model_dump()
    data["user_id"] = current_user.id
    data["created_at"] = datetime.now()
    query = tbl_task.insert().values(**data)
    last_record_id = await database.execute(query)
    logger.info("POST / - created task id=%s", last_record_id)
    return {**data, "id": last_record_id}


@router.put(
    "/{task_id}",
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
async def update_task(
    task_id: int, title: str = None, description: str = None, completed: bool = None
):
    logger.info("PUT /%s - updating task", task_id)
    # Reuse existing 404 behavior from get_task.
    await get_task(task_id)

    update_data = {}
    if title is not None:
        update_data["title"] = title
    if description is not None:
        update_data["description"] = description
    if completed is not None:
        update_data["completed"] = completed

    if not update_data:
        logger.warning("PUT /%s - no fields to update", task_id)
        raise HTTPException(status_code=400, detail=NO_FIELDS_TO_UPDATE)

    query = tbl_task.update().where(tbl_task.c.id == task_id)
    await database.execute(query.values(**update_data))
    logger.info("PUT /%s - task updated", task_id)
    return {"message": "Task updated successfully"}


@router.delete("/{task_id}", responses={404: {"description": TASK_NOT_FOUND}})
async def delete_task(task_id: int):
    logger.info("DELETE /%s - deleting task", task_id)
    await get_task(task_id)

    await database.execute(tbl_task_tags.delete().where(tbl_task_tags.c.task_id == task_id))
    await database.execute(tbl_subtask.delete().where(tbl_subtask.c.task_id == task_id))
    query = tbl_task.delete().where(tbl_task.c.id == task_id)
    await database.execute(query)
    logger.info("DELETE /%s - task deleted", task_id)
    return {"message": "Task deleted successfully"}


@router.get(
    SUBTASKS_PATH, response_model=TaskWithSubTasks, responses={404: {"description": TASK_NOT_FOUND}}
)
async def get_task_with_subtasks(task_id: int):
    logger.info("GET /%s/subtasks - fetching task and subtasks", task_id)
    task = await get_task(task_id)
    subtasks = await get_subtasks_on_task(task_id)
    logger.info("GET /%s/subtasks - fetched %s subtasks", task_id, len(subtasks))
    return {"task": task, "subtasks": subtasks}


@router.post(
    SUBTASK_PATH,
    response_model=SubTaskCreateResponse,
    status_code=201,
    responses={404: {"description": TASK_NOT_FOUND}},
)
async def create_subtask(
    subtask: SubTaskCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    logger.info("POST /subtask - creating subtask for task_id=%s", subtask.task_id)

    await get_task(subtask.task_id)

    data = subtask.model_dump()
    data["user_id"] = current_user.id
    data["created_at"] = datetime.now()
    query = tbl_subtask.insert().values(**data)
    last_record_id = await database.execute(query)
    logger.info("POST /subtask - created subtask id=%s", last_record_id)
    return {**data, "id": last_record_id}


@router.get(
    TASK_SUBTASK_PATH,
    response_model=list[SubTaskCreateResponse],
    responses={404: {"description": TASK_NOT_FOUND}},
)
async def get_subtasks_on_task(task_id: int):
    logger.info("GET /%s/subtask - fetching subtasks", task_id)
    await get_task(task_id)
    query = tbl_subtask.select().where(tbl_subtask.c.task_id == task_id)
    subtasks = await database.fetch_all(query)
    logger.info("GET /%s/subtask - fetched %s subtasks", task_id, len(subtasks))
    return subtasks


@router.post(
    TAGS_PATH,
    response_model=TagResponse,
    responses={
        404: {"description": TASK_NOT_FOUND},
        403: {"description": NOT_AUTHORIZED_MODIFY_TASK},
    },
)
async def create_tag(
    task_id: int,
    tag: TagCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    response: Response,
):
    logger.info("POST /%s/tags - creating tag name=%s", task_id, tag.name)

    task = await get_task(task_id)
    ensure_task_owner(task, current_user, NOT_AUTHORIZED_MODIFY_TASK)
    query = tbl_tag.select().where(
        tbl_tag.c.user_id == current_user.id,
        tbl_tag.c.name == tag.name,
    )
    existing_tag = await database.fetch_one(query)

    if existing_tag:
        tag_record = dict(existing_tag)
    else:
        tag_data = tag.model_dump()
        tag_data["user_id"] = current_user.id
        tag_data["created_at"] = datetime.now()
        insert_query = tbl_tag.insert().values(**tag_data)
        last_record_id = await database.execute(insert_query)
        tag_record = {**tag_data, "id": last_record_id}
        logger.info("POST /%s/tags - created tag id=%s", task_id, last_record_id)

    link_query = tbl_task_tags.select().where(
        tbl_task_tags.c.task_id == task_id,
        tbl_task_tags.c.tag_id == tag_record["id"],
    )
    existing_link = await database.fetch_one(link_query)

    link_created = not existing_link
    if link_created:
        await database.execute(
            tbl_task_tags.insert().values(task_id=task_id, tag_id=tag_record["id"])
        )
    # Keep payload stable while status reflects whether a new link was created.
    set_tag_link_response_status(response, link_created)

    return tag_record


@router.get(
    TAGS_PATH,
    response_model=list[TagResponse],
    responses={
        404: {"description": TASK_NOT_FOUND},
        403: {"description": NOT_AUTHORIZED_VIEW_TAGS},
    },
)
async def get_tags_on_task(
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
):
    logger.info("GET /%s/tags - fetching tags", task_id)
    task = await get_task(task_id)
    ensure_task_owner(task, current_user, NOT_AUTHORIZED_VIEW_TAGS)
    # Build a query to retrieve all tags linked to a specific task.
    query = (
        tbl_tag.select()
        .select_from(tbl_tag.join(tbl_task_tags, tbl_tag.c.id == tbl_task_tags.c.tag_id))
        .where(tbl_task_tags.c.task_id == task_id)
    )
    tags = await database.fetch_all(query)
    logger.info("GET /%s/tags - fetched %s tags", task_id, len(tags))
    return tags
