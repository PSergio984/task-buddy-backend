"""API endpoints for tasks, subtasks, and tags."""

import logging
from typing import Annotated, Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    RATE_LIMIT_SUBTASK_CREATE,
    RATE_LIMIT_SUBTASK_DELETE,
    RATE_LIMIT_SUBTASK_UPDATE,
    RATE_LIMIT_TAG_ATTACH,
    RATE_LIMIT_TAG_CREATE,
    RATE_LIMIT_TAG_CREATE_ATTACH,
    RATE_LIMIT_TAG_DELETE,
    RATE_LIMIT_TAG_DETACH,
    RATE_LIMIT_TAG_UPDATE,
    RATE_LIMIT_TASK_CREATE,
    RATE_LIMIT_TASK_DELETE,
    RATE_LIMIT_TASK_GET,
    RATE_LIMIT_TASK_UPDATE,
)
from app.crud import project as project_crud
from app.crud import tag as tag_crud
from app.crud import task as task_crud
from app.dependencies import get_db
from app.knowledge.history import delete_history_knowledge, ingest_history_task
from app.libs.cache import get_cache_key, get_cached_data, set_cached_data
from app.limiter import limiter
from app.models.tag import Tag
from app.models.task import DeadlineType, SubTask, Task
from app.models.user import User
from app.planner.deadline import propose_deadline
from app.schemas.tag import TagCreate, TagResponse, TagUpdate
from app.schemas.task import (
    SubTaskCreateRequest,
    SubTaskCreateResponse,
    SubTaskUpdateRequest,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskUpdateRequest,
    TaskWithSubTasks,
)
from app.security import get_confirmed_user, get_redis_client

# Constants to avoid duplicated string literals
ROUTER_TAG = "tasks"
TASK_NOT_FOUND = "Task not found"
SUBTASK_NOT_FOUND = "Subtask not found"
BAD_REQUEST = "Bad request"
NO_FIELDS_TO_UPDATE = "No fields to update"
NOT_AUTHORIZED_MODIFY_TASK = "Not authorized to modify this task"
NOT_AUTHORIZED_VIEW_TAGS = "Not authorized to view this task's tags"
TAG_NOT_FOUND = "Tag not found"
INVALID_PROJECT_ID = "Invalid project_id"
MAX_TAGS_EXCEEDED = "Cannot exceed 10 tags per task"
MAX_SUBTASKS_EXCEEDED = "Cannot exceed 50 subtasks per task"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={
        404: {"description": TASK_NOT_FOUND},
        400: {
            "description": "Bad Request - Invalid parameters or missing fields",
            "content": {"application/json": {"example": {"detail": BAD_REQUEST}}},
        },
        401: {"description": "Not authenticated"},
    },
)

logger = logging.getLogger(__name__)


async def invalidate_task_cache(current_user_id: int, task_id: int | None = None) -> None:
    redis = get_redis_client()
    if redis:
        keys = await redis.keys(f"cache:tasks_list:{current_user_id}:*")
        if task_id is not None:
            keys.extend(await redis.keys(f"cache:task_detail:{current_user_id}:{task_id}*"))
        else:
            keys.extend(await redis.keys(f"cache:task_detail:{current_user_id}:*"))
        if keys:
            await redis.delete(*keys)


async def verify_project_ownership(db: AsyncSession, project_id: int | None, user_id: int) -> None:
    if project_id is not None:
        db_project = await project_crud.get_project(db, project_id=project_id, user_id=user_id)
        if not db_project:
            raise HTTPException(status_code=400, detail=INVALID_PROJECT_ID)


async def _validate_tags_limit(db: AsyncSession, tags: list[str] | None, user_id: int) -> None:
    if tags is not None:
        if len(tags) > 10:
            raise HTTPException(status_code=400, detail=MAX_TAGS_EXCEEDED)
        unique_names = list(dict.fromkeys(name.strip() for name in tags if name.strip()))
        existing_tags = await tag_crud.get_tags_by_names(db, user_id=user_id, names=unique_names)
        existing_names = {t.name for t in existing_tags}
        new_tags_count = sum(1 for name in unique_names if name not in existing_names)

        if new_tags_count > 0:
            tag_count_query = select(func.count()).select_from(Tag).where(Tag.user_id == user_id)
            tag_count_res = await db.execute(tag_count_query)
            tag_count = tag_count_res.scalar() or 0
            if tag_count + new_tags_count > 50:
                raise HTTPException(status_code=400, detail="Cannot exceed 50 tags per user")


@router.get(
    "/",
    response_model=list[TaskCreateResponse],
    responses={400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TASK_GET)
async def get_tasks(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    completed: Annotated[bool | None, Query()] = None,
    project_id: Annotated[int | None, Query()] = None,
    tag_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Task]:
    cache_key = get_cache_key(
        "tasks_list",
        current_user.id,
        completed=completed,
        project_id=project_id,
        tag_id=tag_id,
        limit=limit,
        offset=offset,
    )
    cached = await get_cached_data(cache_key, list[TaskCreateResponse])
    if cached is not None:
        return cast(list[Task], cached)

    tasks = await task_crud.get_tasks(
        db,
        user_id=current_user.id,
        completed=completed,
        project_id=project_id,
        tag_id=tag_id,
        limit=limit,
        offset=offset,
    )
    await set_cached_data(cache_key, tasks)
    return tasks


@router.get(
    "/tags",
    response_model=list[TagResponse],
    responses={400: {"description": BAD_REQUEST}},
)
@router.get(
    "/tags/",
    response_model=list[TagResponse],
    responses={400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TASK_GET)
async def get_all_tags(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Tag]:
    return await tag_crud.get_user_tags(db, user_id=current_user.id)


@router.get(
    "/{task_id}",
    response_model=TaskCreateResponse,
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TASK_GET)
async def get_task(
    task_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Task:
    logger.info("GET /%s - fetching task", task_id)
    task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)

    if not task:
        logger.warning("GET /%s - task not found", task_id)
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    return task


@router.post(
    "/",
    response_model=TaskCreateResponse,
    status_code=201,
    responses={400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TASK_CREATE)
async def create_task(
    task: TaskCreateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Task:
    logger.info("POST / - creating task title=%s", task.title)

    if task.subtasks and len(task.subtasks) > 50:
        raise HTTPException(status_code=400, detail=MAX_SUBTASKS_EXCEEDED)

    # Enforce task count limit per user
    task_count_query = select(func.count()).select_from(Task).where(Task.user_id == current_user.id)
    task_count_res = await db.execute(task_count_query)
    task_count = task_count_res.scalar() or 0
    if task_count >= 1000:
        raise HTTPException(status_code=400, detail="Cannot exceed 1000 tasks per user")

    # Enforce tag count limit per user if tags are passed
    await _validate_tags_limit(db, task.tags, current_user.id)

    await verify_project_ownership(db, task.project_id, current_user.id)

    try:
        db_task: Task = await task_crud.create_task(db, user_id=current_user.id, task_in=task)
        if task.due_date is not None:
            db_task.deadline_type = DeadlineType.HARD
        await db.commit()
        await db.refresh(db_task)
    except IntegrityError as e:
        await db.rollback()
        logger.warning("Integrity error creating task: %s", str(e))
        raise HTTPException(status_code=400, detail=INVALID_PROJECT_ID) from e

    # Ensure tags and subtasks are loaded for serialization
    await db_task.awaitable_attrs.tags
    await db_task.awaitable_attrs.subtasks

    if task.due_date is None:
        # D-02/D-05: transient SOFT proposal — response-only, never persisted.
        db_task.proposed_deadline = propose_deadline(task.priority, task.estimated_effort_minutes)
        db_task.deadline_type = DeadlineType.SOFT

    logger.info("POST / - created task id=%s", db_task.id)

    await invalidate_task_cache(current_user.id)

    return db_task


@router.put(
    "/{task_id}",
    response_model=TaskCreateResponse,
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TASK_UPDATE)
async def update_task(
    task_id: int,
    task_update: TaskUpdateRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Task:
    logger.info("PUT /%s - updating task", task_id)
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)
    was_completed = db_task.completed

    # Enforce tag count limit per user if tags are passed
    await _validate_tags_limit(db, task_update.tags, current_user.id)

    update_data = task_update.model_dump(exclude_unset=True)
    if not update_data:
        logger.warning("PUT /%s - no fields to update", task_id)
        raise HTTPException(status_code=400, detail=NO_FIELDS_TO_UPDATE)

    if "project_id" in update_data:
        await verify_project_ownership(db, task_update.project_id, current_user.id)

    try:
        await task_crud.update_task(db, db_task=db_task, task_in=task_update)
        await db.commit()
        await db.refresh(db_task)
    except IntegrityError as e:
        await db.rollback()
        logger.warning("Integrity error updating task: %s", str(e))
        raise HTTPException(status_code=400, detail=INVALID_PROJECT_ID) from e

    # Ensure tags and subtasks are loaded for serialization
    await db_task.awaitable_attrs.tags
    await db_task.awaitable_attrs.subtasks

    completed_now = db_task.completed
    if not was_completed and completed_now:
        # D-05: schedule ingestion — fire-and-forget, never inline.
        background_tasks.add_task(ingest_history_task, db_task.id, current_user.id)
    elif was_completed and not completed_now:
        # D-11: un-complete deletes the history row + chunks.
        try:
            await delete_history_knowledge(db, task_id=db_task.id, user_id=current_user.id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.warning("history cleanup failed for task=%s: %s", db_task.id, exc)

    logger.info("PUT /%s - task updated", task_id)

    await invalidate_task_cache(current_user.id, task_id)

    return db_task


@router.delete(
    "/{task_id}",
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TASK_DELETE)
async def delete_task(
    task_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    logger.info("DELETE /%s - deleting task", task_id)
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    await task_crud.delete_task(db, db_task=db_task, user_id=current_user.id)
    await db.commit()

    logger.info("DELETE /%s - task deleted", task_id)
    await invalidate_task_cache(current_user.id, task_id)
    return {"message": "Task deleted successfully"}


@router.get(
    "/{task_id}/subtask",
    response_model=list[SubTaskCreateResponse],
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TASK_GET)
async def get_subtasks_on_task_list(
    task_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SubTask]:
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)
    return await task_crud.get_subtasks_on_task(db, task_id=task_id)


@router.get(
    "/{task_id}/subtasks",
    response_model=TaskWithSubTasks,
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TASK_GET)
async def get_task_with_subtasks(
    task_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    logger.info("GET /%s/subtasks - fetching task and subtasks", task_id)

    cache_key = get_cache_key("task_detail", current_user.id, task_id=task_id, with_subtasks=True)
    cached = await get_cached_data(cache_key, dict)
    if cached is not None:
        return cached

    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    subtasks = await task_crud.get_subtasks_on_task(db, task_id=task_id)

    logger.info("GET /%s/subtasks - fetched %s subtasks", task_id, len(subtasks))
    result = {"task": db_task, "subtasks": subtasks}
    await set_cached_data(cache_key, result)
    return result


@router.post(
    "/subtask",
    response_model=SubTaskCreateResponse,
    status_code=201,
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_SUBTASK_CREATE)
async def create_subtask(
    subtask: SubTaskCreateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubTask:
    logger.info("POST /subtask - creating subtask for task_id=%s", subtask.task_id)

    db_task = await task_crud.get_task(db, task_id=subtask.task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    existing_subtasks = await task_crud.get_subtasks_on_task(db, task_id=subtask.task_id)
    if len(existing_subtasks) >= 50:
        raise HTTPException(status_code=400, detail=MAX_SUBTASKS_EXCEEDED)

    db_subtask: SubTask = await task_crud.create_subtask(
        db, task_id=subtask.task_id, user_id=current_user.id, subtask_in=subtask
    )
    await db.commit()
    await db.refresh(db_subtask)

    logger.info("POST /subtask - created subtask id=%s", db_subtask.id)
    await invalidate_task_cache(current_user.id, subtask.task_id)
    return db_subtask


@router.get(
    "/subtask/{subtask_id}",
    response_model=SubTaskCreateResponse,
    responses={404: {"description": SUBTASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TASK_GET)
async def get_subtask(
    subtask_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubTask:
    logger.info("GET /subtask/%s - fetching subtask", subtask_id)
    db_subtask = await task_crud.get_subtask(db, subtask_id=subtask_id, user_id=current_user.id)

    if not db_subtask:
        logger.warning("GET /subtask/%s - subtask not found", subtask_id)
        raise HTTPException(status_code=404, detail=SUBTASK_NOT_FOUND)

    logger.info("GET /subtask/%s - subtask found", subtask_id)
    return db_subtask


@router.put(
    "/subtask/{subtask_id}",
    response_model=SubTaskCreateResponse,
    responses={404: {"description": SUBTASK_NOT_FOUND}, 400: {"description": NO_FIELDS_TO_UPDATE}},
)
@limiter.limit(RATE_LIMIT_SUBTASK_UPDATE)
async def update_subtask(
    subtask_id: int,
    subtask_update: SubTaskUpdateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubTask:
    logger.info("PUT /subtask/%s - updating subtask", subtask_id)
    db_subtask = await task_crud.get_subtask(db, subtask_id=subtask_id, user_id=current_user.id)
    if not db_subtask:
        raise HTTPException(status_code=404, detail=SUBTASK_NOT_FOUND)

    update_data = subtask_update.model_dump(exclude_unset=True)
    if not update_data:
        logger.warning("PUT /subtask/%s - no fields to update", subtask_id)
        raise HTTPException(status_code=400, detail=NO_FIELDS_TO_UPDATE)

    await task_crud.update_subtask(db, db_subtask=db_subtask, subtask_in=subtask_update)
    await db.commit()
    await db.refresh(db_subtask)

    logger.info("PUT /subtask/%s - subtask updated", subtask_id)
    await invalidate_task_cache(current_user.id, db_subtask.task_id)
    return db_subtask


@router.delete(
    "/subtask/{subtask_id}",
    responses={404: {"description": SUBTASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_SUBTASK_DELETE)
async def delete_subtask(
    subtask_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    logger.info("DELETE /subtask/%s - deleting subtask", subtask_id)
    db_subtask = await task_crud.get_subtask(db, subtask_id=subtask_id, user_id=current_user.id)
    if not db_subtask:
        raise HTTPException(status_code=404, detail=SUBTASK_NOT_FOUND)

    await task_crud.delete_subtask(db, db_subtask=db_subtask, user_id=current_user.id)
    await db.commit()

    logger.info("DELETE /subtask/%s - subtask deleted", subtask_id)
    await invalidate_task_cache(current_user.id, db_subtask.task_id)
    return {"message": "Subtask deleted successfully"}


@router.post("/{task_id}/subtask/reorder", responses={404: {"description": TASK_NOT_FOUND}})
@limiter.limit(RATE_LIMIT_SUBTASK_UPDATE)
async def reorder_subtasks(
    task_id: int,
    ordered_ids: list[int],
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    logger.info("POST /%s/subtask/reorder - reordering subtasks", task_id)
    # Verify task ownership
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    await task_crud.reorder_subtasks(
        db, task_id=task_id, user_id=current_user.id, ordered_ids=ordered_ids
    )
    await db.commit()
    logger.info("POST /%s/subtask/reorder - subtasks reordered", task_id)
    await invalidate_task_cache(current_user.id, task_id)
    return {"message": "Subtasks reordered successfully"}


# --- Tag Endpoints ---


@router.post(
    "/tags/",
    response_model=TagResponse,
    status_code=201,
    responses={400: {"description": "Tag already exists or invalid request"}},
)
@limiter.limit(RATE_LIMIT_TAG_CREATE)
async def create_tag(
    tag: TagCreate,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Tag:
    existing_tag = await tag_crud.get_tag_by_name(db, user_id=current_user.id, name=tag.name)
    if existing_tag:
        raise HTTPException(status_code=400, detail="Tag already exists")

    # Enforce tag count limit per user
    tag_count_query = select(func.count()).select_from(Tag).where(Tag.user_id == current_user.id)
    tag_count_res = await db.execute(tag_count_query)
    tag_count = tag_count_res.scalar() or 0
    if tag_count >= 50:
        raise HTTPException(status_code=400, detail="Cannot exceed 50 tags per user")

    try:
        db_tag: Tag = await tag_crud.create_tag(db, user_id=current_user.id, tag_in=tag)
        await db.commit()
        await db.refresh(db_tag)
        return db_tag
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Tag already exists") from None


@router.put(
    "/tags/{tag_id}",
    response_model=TagResponse,
    responses={404: {"description": TAG_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TAG_UPDATE)
async def update_tag(
    tag_id: int,
    tag_update: TagUpdate,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Tag:
    # Verify ownership
    query = select(Tag).where(Tag.id == tag_id, Tag.user_id == current_user.id)
    result = await db.execute(query)
    db_tag = result.scalar_one_or_none()

    if not db_tag:
        raise HTTPException(status_code=404, detail=TAG_NOT_FOUND)

    try:
        updated_tag: Tag = await tag_crud.update_tag(
            db, db_tag=db_tag, tag_in=tag_update, user_id=current_user.id
        )
        await db.commit()
        await db.refresh(updated_tag)
        await invalidate_task_cache(current_user.id)
        return updated_tag
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Tag name already exists") from None


@router.delete(
    "/tags/{tag_id}",
    responses={404: {"description": TAG_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TAG_DELETE)
async def delete_tag(
    tag_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    # Verify ownership
    query = select(Tag).where(Tag.id == tag_id, Tag.user_id == current_user.id)
    result = await db.execute(query)
    db_tag = result.scalar_one_or_none()

    if not db_tag:
        raise HTTPException(status_code=404, detail=TAG_NOT_FOUND)

    await tag_crud.delete_tag(db, db_tag=db_tag, user_id=current_user.id)
    await db.commit()
    await invalidate_task_cache(current_user.id)
    return {"message": "Tag deleted successfully"}


@router.post("/tags/reorder")
@limiter.limit(RATE_LIMIT_TAG_UPDATE)
async def reorder_tags(
    ordered_ids: list[int],
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    await tag_crud.reorder_tags(db, user_id=current_user.id, ordered_ids=ordered_ids)
    await db.commit()
    await invalidate_task_cache(current_user.id)
    return {"message": "Tags reordered successfully"}


@router.post(
    "/{task_id}/tags",
    response_model=TagResponse,
    status_code=201,
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TAG_CREATE_ATTACH)
async def create_and_attach_tag(
    task_id: int,
    tag_in: TagCreate,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Tag:
    # Verify task ownership
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    existing_tags = await tag_crud.get_tags_on_task(db, task_id=task_id)
    normalized_name = tag_in.name.strip()
    tag_names = [t.name.strip() for t in existing_tags]
    if normalized_name not in tag_names and len(existing_tags) >= 10:
        raise HTTPException(status_code=400, detail=MAX_TAGS_EXCEEDED)

    try:
        # Check if tag already exists for user
        db_tag = await tag_crud.get_tag_by_name(db, user_id=current_user.id, name=tag_in.name)
        if not db_tag:
            # Enforce tag count limit per user
            tag_count_query = (
                select(func.count()).select_from(Tag).where(Tag.user_id == current_user.id)
            )
            tag_count_res = await db.execute(tag_count_query)
            tag_count = tag_count_res.scalar() or 0
            if tag_count >= 50:
                raise HTTPException(status_code=400, detail="Cannot exceed 50 tags per user")

            db_tag = await tag_crud.create_tag(db, user_id=current_user.id, tag_in=tag_in)
            await db.flush()  # Get the tag ID

        # Attach to task
        await tag_crud.attach_tag_to_task(
            db, task_id=task_id, tag_id=db_tag.id, user_id=current_user.id
        )

        await db.commit()
        await db.refresh(db_tag)
        await invalidate_task_cache(current_user.id, task_id)
        return db_tag
    except IntegrityError:
        await db.rollback()
        # Retry logic: tag might have been created by another request
        db_tag = await tag_crud.get_tag_by_name(db, user_id=current_user.id, name=tag_in.name)
        if not db_tag:
            raise HTTPException(status_code=400, detail="Failed to create or attach tag") from None

        # Try attaching again if it was just the creation that failed
        try:
            await tag_crud.attach_tag_to_task(
                db, task_id=task_id, tag_id=db_tag.id, user_id=current_user.id
            )
            await db.commit()
            await db.refresh(db_tag)
            await invalidate_task_cache(current_user.id, task_id)
            return db_tag
        except IntegrityError:
            await db.rollback()
            await db.refresh(db_tag)
            return db_tag


@router.get(
    "/{task_id}/tags",
    response_model=list[TagResponse],
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TASK_GET)
async def get_tags_on_task(
    task_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Tag]:
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    return await tag_crud.get_tags_on_task(db, task_id=task_id)


@router.post(
    "/{task_id}/tags/{tag_id}",
    responses={404: {"description": "Task or Tag not found"}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TAG_ATTACH)
async def attach_tag_to_task(
    task_id: int,
    tag_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    # Verify ownership of both task and tag
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    query_tag = select(Tag).where(Tag.id == tag_id, Tag.user_id == current_user.id)
    result_tag = await db.execute(query_tag)
    if not result_tag.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=TAG_NOT_FOUND)

    existing_tags = await tag_crud.get_tags_on_task(db, task_id=task_id)
    existing_tag_ids = [t.id for t in existing_tags]
    if tag_id not in existing_tag_ids and len(existing_tags) >= 10:
        raise HTTPException(status_code=400, detail=MAX_TAGS_EXCEEDED)

    try:
        attached = await tag_crud.attach_tag_to_task(
            db, task_id=task_id, tag_id=tag_id, user_id=current_user.id
        )
        if not attached:
            return {"message": "Tag already attached"}
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"message": "Tag already attached"}

    await invalidate_task_cache(current_user.id, task_id)
    return {"message": "Tag attached successfully"}


@router.delete(
    "/{task_id}/tags/{tag_id}",
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit(RATE_LIMIT_TAG_DETACH)
async def detach_tag_from_task(
    task_id: int,
    tag_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    # Verify ownership
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    await tag_crud.detach_tag_from_task(db, task_id=task_id, tag_id=tag_id, user_id=current_user.id)

    await db.commit()
    await invalidate_task_cache(current_user.id, task_id)
    return {"message": "Tag detached successfully"}
