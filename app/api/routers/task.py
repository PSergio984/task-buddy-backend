import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import group as group_crud
from app.crud import tag as tag_crud
from app.crud import task as task_crud
from app.dependencies import get_db
from app.internal.audit import log_action
from app.models.tag import Tag
from app.models.user import User
from app.schemas.enums import AuditAction
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
INVALID_GROUP_ID = "Invalid group_id"

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


async def verify_group_ownership(db: AsyncSession, group_id: int | None, user_id: int) -> None:
    if group_id is not None:
        db_group = await group_crud.get_group(db, group_id=group_id, user_id=user_id)
        if not db_group:
            raise HTTPException(status_code=400, detail=INVALID_GROUP_ID)


from sqlalchemy.orm import selectinload, attributes

@router.get("/", response_model=list[TaskCreateResponse], responses={400: {"description": BAD_REQUEST}})
async def get_all_tasks(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    completed: Annotated[bool | None, Query()] = None,
    group_id: Annotated[int | None, Query()] = None,
    tag_id: Annotated[int | None, Query()] = None,
):
    tasks = await task_crud.get_tasks(
        db, user_id=current_user.id, completed=completed, group_id=group_id, tag_id=tag_id
    )
    
    response_list = []
    for task in tasks:
        await task.awaitable_attrs.tags
        task_data = {
            "id": task.id,
            "user_id": task.user_id,
            "group_id": task.group_id,
            "title": task.title,
            "description": task.description,
            "completed": task.completed,
            "priority": task.priority,
            "due_date": task.due_date,
            "created_at": task.created_at,
            "tags": [
                {"id": tag.id, "user_id": tag.user_id, "name": tag.name, "created_at": tag.created_at}
                for tag in task.tags
            ]
        }
        response_list.append(task_data)

    return response_list

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

    await task.awaitable_attrs.tags
    return {
        "id": task.id,
        "user_id": task.user_id,
        "group_id": task.group_id,
        "title": task.title,
        "description": task.description,
        "completed": task.completed,
        "priority": task.priority,
        "due_date": task.due_date,
        "created_at": task.created_at,
        "tags": [
            {"id": tag.id, "user_id": tag.user_id, "name": tag.name, "created_at": tag.created_at}
            for tag in task.tags
        ]
    }

@router.post("/", response_model=TaskCreateResponse, status_code=201, responses={400: {"description": BAD_REQUEST}})
async def create_task(
    task_in: TaskCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("POST / - creating task title=%s", task_in.title)

    await verify_group_ownership(db, task_in.group_id, current_user.id)
    db_task = await task_crud.create_task(db, user_id=current_user.id, task_in=task_in)

    # Flush to get ID for audit log
    await db.flush()
    await db.refresh(db_task)

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.CREATE,
        target_type="TASK",
        target_id=db_task.id,
        details=f"Created task: {db_task.title}",
    )
    await db.commit()
    await db.refresh(db_task)

    # Eager load tags and return manually serialized dictionary
    await db_task.awaitable_attrs.tags

    logger.info("POST / - created task id=%s", db_task.id)
    return {
        "id": db_task.id,
        "user_id": db_task.user_id,
        "group_id": db_task.group_id,
        "title": db_task.title,
        "description": db_task.description,
        "completed": db_task.completed,
        "priority": db_task.priority,
        "due_date": db_task.due_date,
        "created_at": db_task.created_at,
        "tags": [
            {"id": tag.id, "user_id": tag.user_id, "name": tag.name, "created_at": tag.created_at}
            for tag in db_task.tags
        ]
    }


@router.put(
    "/{task_id}",
    responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
async def update_task(
    task_id: int,
    task_update: TaskUpdateRequest,
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

    if "group_id" in update_data:
        await verify_group_ownership(db, task_update.group_id, current_user.id)

    await task_crud.update_task(db, db_task=db_task, task_in=task_update)

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type="TASK",
        target_id=task_id,
        details=f"Updated task '{db_task.title}': {', '.join(update_data.keys())}",
    )
    await db.commit()

    logger.info("PUT /%s - task updated", task_id)
    return {"message": "Task updated successfully"}


@router.delete("/{task_id}", responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}})
async def delete_task(
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("DELETE /%s - deleting task", task_id)
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    task_title = db_task.title
    await task_crud.delete_task(db, db_task=db_task)

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.DELETE,
        target_type="TASK",
        target_id=task_id,
        details=f"Deleted task: {task_title}",
    )
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
async def create_subtask(
    subtask_in: SubTaskCreateRequest,
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

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.CREATE,
        target_type="SUBTASK",
        target_id=db_subtask.id,
        details=f"Created subtask for task {subtask_in.task_id}: {subtask_in.title}",
    )
    await db.commit()

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
    responses={404: {"description": SUBTASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}},
)
async def update_subtask(
    subtask_id: int,
    subtask_update: SubTaskUpdateRequest,
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

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type="SUBTASK",
        target_id=subtask_id,
        details=f"Updated subtask '{db_subtask.title}' on task {db_subtask.task_id}: {', '.join(update_data.keys())}",
    )
    await db.commit()

    logger.info("PUT /subtask/%s - subtask updated", subtask_id)
    return {"message": "Subtask updated successfully"}


@router.delete("/subtask/{subtask_id}", responses={404: {"description": SUBTASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}})
async def delete_subtask(
    subtask_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("DELETE /subtask/%s - deleting subtask", subtask_id)
    db_subtask = await task_crud.get_subtask(db, subtask_id=subtask_id, user_id=current_user.id)
    if not db_subtask:
        raise HTTPException(status_code=404, detail=SUBTASK_NOT_FOUND)

    subtask_title = db_subtask.title
    task_id = db_subtask.task_id
    await task_crud.delete_subtask(db, db_subtask=db_subtask)

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.DELETE,
        target_type="SUBTASK",
        target_id=subtask_id,
        details=f"Deleted subtask '{subtask_title}' from task {task_id}",
    )
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
async def create_tag(
    tag_in: TagCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing_tag = await tag_crud.get_tag_by_name(db, user_id=current_user.id, name=tag_in.name)
    if existing_tag:
        raise HTTPException(status_code=400, detail="Tag already exists")

    db_tag = await tag_crud.create_tag(db, user_id=current_user.id, tag_in=tag_in)
    await db.commit()
    await db.refresh(db_tag)
    return db_tag


@router.delete("/tags/{tag_id}", responses={404: {"description": TAG_NOT_FOUND}, 400: {"description": BAD_REQUEST}})
async def delete_tag(
    tag_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Verify ownership
    query = select(Tag).where(Tag.id == tag_id, Tag.user_id == current_user.id)
    result = await db.execute(query)
    db_tag = result.scalar_one_or_none()

    if not db_tag:
        raise HTTPException(status_code=404, detail=TAG_NOT_FOUND)

    await tag_crud.delete_tag(db, db_tag=db_tag)
    await db.commit()
    return {"message": "Tag deleted successfully"}


@router.post("/{task_id}/tags", response_model=TagResponse, status_code=201, responses={400: {"description": BAD_REQUEST}})
async def create_and_attach_tag(
    task_id: int,
    tag_in: TagCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Verify task ownership
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    # Check if tag already exists for user
    db_tag = await tag_crud.get_tag_by_name(db, user_id=current_user.id, name=tag_in.name)
    if not db_tag:
        db_tag = await tag_crud.create_tag(db, user_id=current_user.id, tag_in=tag_in)
        await db.flush() # Get the tag ID

    # Attach to task
    await tag_crud.attach_tag_to_task(db, task_id=task_id, tag_id=db_tag.id)
    await db.commit()
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
async def attach_tag_to_task(
    task_id: int,
    tag_id: int,
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

    attached = await tag_crud.attach_tag_to_task(db, task_id=task_id, tag_id=tag_id)
    if not attached:
        return {"message": "Tag already attached"}

    await db.commit()
    return {"message": "Tag attached successfully"}


@router.delete("/{task_id}/tags/{tag_id}", responses={404: {"description": TASK_NOT_FOUND}, 400: {"description": BAD_REQUEST}})
async def detach_tag_from_task(
    task_id: int,
    tag_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Verify ownership
    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    await tag_crud.detach_tag_from_task(db, task_id=task_id, tag_id=tag_id)
    await db.commit()
    return {"message": "Tag detached successfully"}

