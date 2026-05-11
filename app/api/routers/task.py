import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import project as project_crud
from app.crud import tag as tag_crud
from app.crud import task as task_crud
from app.dependencies import get_db
from app.limiter import limiter
from app.models.tag import Tag
from app.models.user import User
from app.schemas.tag import TagCreate, TagResponse
from app.schemas.task import (
    SubTaskCreateRequest,
    SubTaskCreateResponse,
    SubTaskUpdateRequest,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskUpdateRequest,
    TaskWithSubTasks,
)
from app.security import get_current_user

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

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={
        404: {"description": TASK_NOT_FOUND},
        400: {
            "description": "Bad Request - Invalid parameters or missing fields",
            "content": {
                "application/json": {
                    "example": {"detail": BAD_REQUEST}
                }
            }
        },
        401: {"description": "Not authenticated"},
    },
)

logger = logging.getLogger(__name__)


async def verify_project_ownership(db: AsyncSession, project_id: int | None, user_id: int) -> None:
    if project_id is not None:
        db_project = await project_crud.get_project(db, project_id=project_id, user_id=user_id)
        if not db_project:
            raise HTTPException(status_code=400, detail=INVALID_PROJECT_ID)




@router.get("/", response_model=list[TaskCreateResponse], responses={400: {"description": BAD_REQUEST}})
async def get_all_tasks(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    completed: Annotated[bool | None, Query()] = None,
    project_id: Annotated[int | None, Query()] = None,
    tag_id: Annotated[int | None, Query()] = None,
):
    tasks = await task_crud.get_tasks(
        db, user_id=current_user.id, completed=completed, project_id=project_id, tag_id=tag_id
    )
    return tasks

@router.get(
    "/{task_id}",
    response_model=TaskCreateResponse,
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
async def get_task(
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("GET /%s - fetching task", task_id)
    task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)

    if not task:
        logger.warning("GET /%s - task not found", task_id)
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    return task

@router.post("/", response_model=TaskCreateResponse, status_code=201, responses={400: {"description": BAD_REQUEST}})
@limiter.limit("20/minute")
async def create_task(
    task_in: TaskCreateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("POST / - creating task title=%s", task_in.title)

    await verify_project_ownership(db, task_in.project_id, current_user.id)

    try:
        db_task = await task_crud.create_task(db, user_id=current_user.id, task_in=task_in)
        await db.commit()
        await db.refresh(db_task)
    except IntegrityError as e:
        await db.rollback()
        logger.warning("Integrity error creating task: %s", str(e))
        raise HTTPException(status_code=400, detail=INVALID_PROJECT_ID) from e

    # Ensure tags and subtasks are loaded for serialization
    await db_task.awaitable_attrs.tags
    await db_task.awaitable_attrs.subtasks

    logger.info("POST / - created task id=%s", db_task.id)
    return db_task


@router.put(
    "/{task_id}",
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit("30/minute")
async def update_task(
    task_id: int,
    task_update: TaskUpdateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("PUT /%s - updating task", task_id)
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

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

    logger.info("PUT /%s - task updated", task_id)
    return db_task


@router.delete("/{task_id}", responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}})
@limiter.limit("20/minute")
async def delete_task(
    task_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("DELETE /%s - deleting task", task_id)
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    await task_crud.delete_task(db, db_task=db_task, user_id=current_user.id)
    await db.commit()

    logger.info("DELETE /%s - task deleted", task_id)
    return {"message": "Task deleted successfully"}


@router.get(
    "/{task_id}/subtask",
    response_model=list[SubTaskCreateResponse],
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
async def get_subtasks_on_task_list(
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)
    return await task_crud.get_subtasks_on_task(db, task_id=task_id)


@router.get(
    "/{task_id}/subtasks", response_model=TaskWithSubTasks, responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}}
)
async def get_task_with_subtasks(
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("GET /%s/subtasks - fetching task and subtasks", task_id)
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    subtasks = await task_crud.get_subtasks_on_task(db, task_id=task_id)

    logger.info("GET /%s/subtasks - fetched %s subtasks", task_id, len(subtasks))
    return {"task": db_task, "subtasks": subtasks}


@router.post(
    "/subtask",
    response_model=SubTaskCreateResponse,
    status_code=201,
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
@limiter.limit("30/minute")
async def create_subtask(
    subtask_in: SubTaskCreateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("POST /subtask - creating subtask for task_id=%s", subtask_in.task_id)

    db_task = await task_crud.get_task(db, task_id=subtask_in.task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    db_subtask = await task_crud.create_subtask(db, task_id=subtask_in.task_id, user_id=current_user.id, subtask_in=subtask_in)
    await db.commit()
    await db.refresh(db_subtask)

    logger.info("POST /subtask - created subtask id=%s", db_subtask.id)
    return db_subtask


@router.get(
    "/subtask/{subtask_id}",
    response_model=SubTaskCreateResponse,
    responses={404: {"description": SUBTASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
async def get_subtask(
    subtask_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("GET /subtask/%s - fetching subtask", subtask_id)
    db_subtask = await task_crud.get_subtask(db, subtask_id=subtask_id, user_id=current_user.id)

    if not db_subtask:
        logger.warning("GET /subtask/%s - subtask not found", subtask_id)
        raise HTTPException(status_code=404, detail=SUBTASK_NOT_FOUND)

    logger.info("GET /subtask/%s - subtask found", subtask_id)
    return db_subtask


@router.put(
    "/subtask/{subtask_id}",
    responses={404: {"description": SUBTASK_NOT_FOUND}, 400: {"description": NO_FIELDS_TO_UPDATE}},
)
@limiter.limit("30/minute")
async def update_subtask(
    subtask_id: int,
    subtask_update: SubTaskUpdateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
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
    return {"message": "Subtask updated successfully"}


@router.delete("/subtask/{subtask_id}", responses={404: {"description": SUBTASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}})
@limiter.limit("20/minute")
async def delete_subtask(
    subtask_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("DELETE /subtask/%s - deleting subtask", subtask_id)
    db_subtask = await task_crud.get_subtask(db, subtask_id=subtask_id, user_id=current_user.id)
    if not db_subtask:
        raise HTTPException(status_code=404, detail=SUBTASK_NOT_FOUND)

    await task_crud.delete_subtask(db, db_subtask=db_subtask, user_id=current_user.id)
    await db.commit()

    logger.info("DELETE /subtask/%s - subtask deleted", subtask_id)
    return {"message": "Subtask deleted successfully"}


# --- Tag Endpoints ---

@router.get("/tags/", response_model=list[TagResponse], responses={400: {"description": BAD_REQUEST}})
async def get_all_tags(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await tag_crud.get_user_tags(db, user_id=current_user.id)


@router.post("/tags/", response_model=TagResponse, status_code=201, responses={400: {"description": "Tag already exists or invalid request"}})
@limiter.limit("20/minute")
async def create_tag(
    tag_in: TagCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing_tag = await tag_crud.get_tag_by_name(db, user_id=current_user.id, name=tag_in.name)
    if existing_tag:
        raise HTTPException(status_code=400, detail="Tag already exists")

    try:
        db_tag = await tag_crud.create_tag(db, user_id=current_user.id, tag_in=tag_in)
        await db.commit()
        await db.refresh(db_tag)
        return db_tag
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Tag already exists")


@router.delete("/tags/{tag_id}", responses={404: {"description": TAG_NOT_FOUND}, 400: {"description": BAD_REQUEST}})
@limiter.limit("20/minute")
async def delete_tag(
    tag_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Verify ownership
    query = select(Tag).where(Tag.id == tag_id, Tag.user_id == current_user.id)
    result = await db.execute(query)
    db_tag = result.scalar_one_or_none()

    if not db_tag:
        raise HTTPException(status_code=404, detail=TAG_NOT_FOUND)

    await tag_crud.delete_tag(db, db_tag=db_tag, user_id=current_user.id)
    await db.commit()
    return {"message": "Tag deleted successfully"}


@router.post("/{task_id}/tags", response_model=TagResponse, status_code=201, responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}})
@limiter.limit("30/minute")
async def create_and_attach_tag(
    task_id: int,
    tag_in: TagCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Verify task ownership
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    try:
        # Check if tag already exists for user
        db_tag = await tag_crud.get_tag_by_name(db, user_id=current_user.id, name=tag_in.name)
        if not db_tag:
            db_tag = await tag_crud.create_tag(db, user_id=current_user.id, tag_in=tag_in)
            await db.flush() # Get the tag ID

        # Attach to task
        await tag_crud.attach_tag_to_task(db, task_id=task_id, tag_id=db_tag.id, user_id=current_user.id)

        await db.commit()
        await db.refresh(db_tag)
        return db_tag
    except IntegrityError:
        await db.rollback()
        # Retry logic: tag might have been created by another request
        db_tag = await tag_crud.get_tag_by_name(db, user_id=current_user.id, name=tag_in.name)
        if not db_tag:
            raise HTTPException(status_code=400, detail="Failed to create or attach tag")
        
        # Try attaching again if it was just the creation that failed
        try:
            await tag_crud.attach_tag_to_task(db, task_id=task_id, tag_id=db_tag.id, user_id=current_user.id)
            await db.commit()
            await db.refresh(db_tag)
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
async def get_tags_on_task(
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    return await tag_crud.get_tags_on_task(db, task_id=task_id)


@router.post("/{task_id}/tags/{tag_id}", responses={404: {"description": "Task or Tag not found"}, 400: {"description": BAD_REQUEST}})
@limiter.limit("30/minute")
async def attach_tag_to_task(
    task_id: int,
    tag_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Verify ownership of both task and tag
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    query_tag = select(Tag).where(Tag.id == tag_id, Tag.user_id == current_user.id)
    result_tag = await db.execute(query_tag)
    if not result_tag.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=TAG_NOT_FOUND)

    try:
        attached = await tag_crud.attach_tag_to_task(db, task_id=task_id, tag_id=tag_id, user_id=current_user.id)
        if not attached:
            return {"message": "Tag already attached"}
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"message": "Tag already attached"}

    return {"message": "Tag attached successfully"}


@router.delete("/{task_id}/tags/{tag_id}", responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}})
@limiter.limit("30/minute")
async def detach_tag_from_task(
    task_id: int,
    tag_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Verify ownership
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    await tag_crud.detach_tag_from_task(db, task_id=task_id, tag_id=tag_id, user_id=current_user.id)

    await db.commit()
    return {"message": "Tag detached successfully"}

