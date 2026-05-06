import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, Query

from app.database import database, tbl_subtask, tbl_task, tbl_tag, tbl_task_tags
from app.models.task import (
    SubTaskCreateRequest,
    SubTaskCreateResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskWithSubTasks,
    TaskUpdateRequest,
    SubTaskUpdateRequest,
)
from app.models.tag import TagResponse, TagCreate

from app.models.user import User
from app.security import get_current_user
from app.internal.audit import log_action

# Constants to avoid duplicated string literals
ROUTER_TAG = "tasks"
TASK_NOT_FOUND = "Task not found"
SUBTASK_NOT_FOUND = "Subtask not found"
BAD_REQUEST = "Bad request"
NO_FIELDS_TO_UPDATE = "No fields to update"
NOT_AUTHORIZED_MODIFY_TASK = "Not authorized to modify this task"
NOT_AUTHORIZED_VIEW_TAGS = "Not authorized to view this task's tags"
SUBTASK_PATH = "/subtask"
SUBTASKS_PATH = "/{task_id}/subtasks"
TASK_SUBTASK_PATH = "/{task_id}/subtask"
TAGS_PATH = "/{task_id}/tags"
TASK_TAG_DETACH_PATH = "/{task_id}/tags/{tag_id}"
TAG_DELETE_PATH = "/tags/{tag_id}"

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
async def get_all_tasks(
    current_user: Annotated[User, Depends(get_current_user)],
    completed: Annotated[bool | None, Query()] = None
):
    logger.info("GET / - fetching tasks for user %s", current_user.id)
    query = tbl_task.select().where(tbl_task.c.user_id == current_user.id)
    
    if completed is not None:
        query = query.where(tbl_task.c.completed == completed)
        
    tasks = await database.fetch_all(query)
    logger.info("GET / - fetched %s tasks", len(tasks))
    return tasks


@router.get(
    "/{task_id}",
    response_model=TaskCreateResponse,
    responses={404: {"description": TASK_NOT_FOUND}},
)
async def get_task(task_id: int, current_user: Annotated[User, Depends(get_current_user)]):
    logger.info("GET /%s - fetching task", task_id)
    query = tbl_task.select().where(
        (tbl_task.c.id == task_id) & (tbl_task.c.user_id == current_user.id)
    )
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

    await log_action(
        user_id=current_user.id,
        action="CREATE",
        target_type="TASK",
        target_id=last_record_id,
        details=f"Created task: {task.title}",
    )

    logger.info("POST / - created task id=%s", last_record_id)
    return {**data, "id": last_record_id}


@router.put(
    "/{task_id}",
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
async def update_task(
    task_id: int,
    task_update: TaskUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    logger.info("PUT /%s - updating task", task_id)
    # Reuse existing 404 behavior from get_task.
    await get_task(task_id, current_user)

    update_data = task_update.model_dump(exclude_unset=True)

    if not update_data:
        logger.warning("PUT /%s - no fields to update", task_id)
        raise HTTPException(status_code=400, detail=NO_FIELDS_TO_UPDATE)

    query = tbl_task.update().where(tbl_task.c.id == task_id)
    await database.execute(query.values(**update_data))

    await log_action(
        user_id=current_user.id,
        action="UPDATE",
        target_type="TASK",
        target_id=task_id,
        details=f"Updated task fields: {', '.join(update_data.keys())}",
    )

    logger.info("PUT /%s - task updated", task_id)
    return {"message": "Task updated successfully"}


@router.delete("/{task_id}", responses={404: {"description": TASK_NOT_FOUND}})
async def delete_task(task_id: int, current_user: Annotated[User, Depends(get_current_user)]):
    logger.info("DELETE /%s - deleting task", task_id)
    await get_task(task_id, current_user)

    await database.execute(tbl_task_tags.delete().where(tbl_task_tags.c.task_id == task_id))
    await database.execute(tbl_subtask.delete().where(tbl_subtask.c.task_id == task_id))
    query = tbl_task.delete().where(tbl_task.c.id == task_id)
    await database.execute(query)

    await log_action(
        user_id=current_user.id, action="DELETE", target_type="TASK", target_id=task_id
    )

    logger.info("DELETE /%s - task deleted", task_id)
    return {"message": "Task deleted successfully"}


@router.get(
    SUBTASKS_PATH, response_model=TaskWithSubTasks, responses={404: {"description": TASK_NOT_FOUND}}
)
async def get_task_with_subtasks(
    task_id: int, current_user: Annotated[User, Depends(get_current_user)]
):
    logger.info("GET /%s/subtasks - fetching task and subtasks", task_id)
    task = await get_task(task_id, current_user)
    subtasks = await get_subtasks_on_task(task_id, current_user)
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

    await get_task(subtask.task_id, current_user)

    data = subtask.model_dump()
    data["user_id"] = current_user.id
    data["created_at"] = datetime.now()
    query = tbl_subtask.insert().values(**data)
    last_record_id = await database.execute(query)

    await log_action(
        user_id=current_user.id,
        action="CREATE",
        target_type="SUBTASK",
        target_id=last_record_id,
        details=f"Created subtask for task {subtask.task_id}: {subtask.title}",
    )

    logger.info("POST /subtask - created subtask id=%s", last_record_id)
    return {**data, "id": last_record_id}


@router.get(
    TASK_SUBTASK_PATH,
    response_model=list[SubTaskCreateResponse],
    responses={404: {"description": TASK_NOT_FOUND}},
)
async def get_subtasks_on_task(
    task_id: int, current_user: Annotated[User, Depends(get_current_user)]
):
    logger.info("GET /%s/subtask - fetching subtasks", task_id)
    await get_task(task_id, current_user)
    query = tbl_subtask.select().where(tbl_subtask.c.task_id == task_id)
    subtasks = await database.fetch_all(query)
    logger.info("GET /%s/subtask - fetched %s subtasks", task_id, len(subtasks))
    return subtasks


@router.get(
    "/subtask/{subtask_id}",
    response_model=SubTaskCreateResponse,
    responses={404: {"description": SUBTASK_NOT_FOUND}},
)
async def get_subtask(subtask_id: int, current_user: Annotated[User, Depends(get_current_user)]):
    logger.info("GET /subtask/%s - fetching subtask", subtask_id)
    query = tbl_subtask.select().where(
        (tbl_subtask.c.id == subtask_id) & (tbl_subtask.c.user_id == current_user.id)
    )
    subtask = await database.fetch_one(query)

    if not subtask:
        logger.warning("GET /subtask/%s - subtask not found", subtask_id)
        raise HTTPException(status_code=404, detail=SUBTASK_NOT_FOUND)

    logger.info("GET /subtask/%s - subtask found", subtask_id)
    return subtask


@router.put(
    "/subtask/{subtask_id}",
    responses={404: {"description": SUBTASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
async def update_subtask(
    subtask_id: int,
    subtask_update: SubTaskUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    logger.info("PUT /subtask/%s - updating subtask", subtask_id)
    await get_subtask(subtask_id, current_user)

    update_data = subtask_update.model_dump(exclude_unset=True)

    if not update_data:
        logger.warning("PUT /subtask/%s - no fields to update", subtask_id)
        raise HTTPException(status_code=400, detail=NO_FIELDS_TO_UPDATE)

    query = tbl_subtask.update().where(tbl_subtask.c.id == subtask_id)
    await database.execute(query.values(**update_data))

    await log_action(
        user_id=current_user.id,
        action="UPDATE",
        target_type="SUBTASK",
        target_id=subtask_id,
        details=f"Updated subtask fields: {', '.join(update_data.keys())}",
    )

    logger.info("PUT /subtask/%s - subtask updated", subtask_id)
    return {"message": "Subtask updated successfully"}


@router.delete("/subtask/{subtask_id}", responses={404: {"description": SUBTASK_NOT_FOUND}})
async def delete_subtask(subtask_id: int, current_user: Annotated[User, Depends(get_current_user)]):
    logger.info("DELETE /subtask/%s - deleting subtask", subtask_id)
    await get_subtask(subtask_id, current_user)

    query = tbl_subtask.delete().where(tbl_subtask.c.id == subtask_id)
    await database.execute(query)

    await log_action(
        user_id=current_user.id, action="DELETE", target_type="SUBTASK", target_id=subtask_id
    )

    logger.info("DELETE /subtask/%s - subtask deleted", subtask_id)
    return {"message": "Subtask deleted successfully"}


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

    task = await get_task(task_id, current_user)
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

        await log_action(
            user_id=current_user.id,
            action="CREATE",
            target_type="TAG",
            target_id=last_record_id,
            details=f"Created tag: {tag.name}",
        )

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

        await log_action(
            user_id=current_user.id,
            action="ATTACH",
            target_type="TAG",
            target_id=tag_record["id"],
            details=f"Attached tag {tag.name} to task {task_id}",
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
    task = await get_task(task_id, current_user)
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


@router.delete(TASK_TAG_DETACH_PATH, responses={404: {"description": TASK_NOT_FOUND}})
async def detach_tag(
    task_id: int,
    tag_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
):
    logger.info("DELETE /%s/tags/%s - detaching tag", task_id, tag_id)
    await get_task(task_id, current_user)
    
    # Check if link exists
    query = tbl_task_tags.select().where(
        (tbl_task_tags.c.task_id == task_id) & (tbl_task_tags.c.tag_id == tag_id)
    )
    link = await database.fetch_one(query)
    if not link:
        logger.warning("DELETE /%s/tags/%s - link not found", task_id, tag_id)
        raise HTTPException(status_code=404, detail="Tag not attached to this task")

    await database.execute(
        tbl_task_tags.delete().where(
            (tbl_task_tags.c.task_id == task_id) & (tbl_task_tags.c.tag_id == tag_id)
        )
    )

    await log_action(
        user_id=current_user.id,
        action="DETACH",
        target_type="TAG",
        target_id=tag_id,
        details=f"Detached tag {tag_id} from task {task_id}",
    )

    logger.info("DELETE /%s/tags/%s - tag detached", task_id, tag_id)
    return {"message": "Tag detached successfully"}


@router.delete(TAG_DELETE_PATH, responses={404: {"description": "Tag not found"}})
async def delete_tag(
    tag_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
):
    logger.info("DELETE /tags/%s - deleting tag", tag_id)
    
    # Verify ownership
    query = tbl_tag.select().where(
        (tbl_tag.c.id == tag_id) & (tbl_tag.c.user_id == current_user.id)
    )
    tag = await database.fetch_one(query)
    if not tag:
        logger.warning("DELETE /tags/%s - tag not found", tag_id)
        raise HTTPException(status_code=404, detail="Tag not found")

    # tbl_task_tags will be cleaned up by CASCADE on tag_id
    await database.execute(tbl_tag.delete().where(tbl_tag.c.id == tag_id))

    await log_action(
        user_id=current_user.id,
        action="DELETE",
        target_type="TAG",
        target_id=tag_id,
        details=f"Deleted tag: {tag.name}",
    )

    logger.info("DELETE /tags/%s - tag deleted", tag_id)
    return {"message": "Tag deleted successfully"}
