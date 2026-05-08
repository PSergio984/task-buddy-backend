import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import group as group_crud
from app.crud import task as task_crud
from app.dependencies import get_db
from app.internal.audit import log_action
from app.models.user import User
from app.schemas.enums import AuditAction
from app.schemas.group import GroupCreateRequest, GroupResponse, GroupUpdateRequest
from app.schemas.task import TaskCreateResponse
from app.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["groups"])

# Error Messages
GROUP_NOT_FOUND = "Group not found"
NO_FIELDS_TO_UPDATE = "No fields to update"

@router.get("/", response_model=list[GroupResponse])
async def list_groups(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("GET / - listing groups for user_id=%s", current_user.id)
    return await group_crud.get_groups(db, user_id=current_user.id)

@router.post("/", response_model=GroupResponse, status_code=201)
async def create_group(
    group_in: GroupCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("POST / - creating group name=%s", group_in.name)

    db_group = await group_crud.create_group(db, user_id=current_user.id, group_in=group_in)

    # Flush to get ID for audit log
    await db.flush()
    await db.refresh(db_group)

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.CREATE,
        target_type="GROUP",
        target_id=db_group.id,
        details=f"Created group: {db_group.name}",
    )
    await db.commit()
    await db.refresh(db_group)

    logger.info("POST / - created group id=%s", db_group.id)
    return db_group

@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("GET /%s - getting group", group_id)
    db_group = await group_crud.get_group(db, group_id=group_id, user_id=current_user.id)
    if not db_group:
        logger.warning("GET /%s - group not found", group_id)
        raise HTTPException(status_code=404, detail=GROUP_NOT_FOUND)

    logger.info("GET /%s - group found", group_id)
    return db_group

@router.get("/{group_id}/tasks", response_model=list[TaskCreateResponse])
async def list_group_tasks(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("GET /%s/tasks - listing tasks in group", group_id)
    # Verify ownership
    db_group = await group_crud.get_group(db, group_id=group_id, user_id=current_user.id)
    if not db_group:
        logger.warning("GET /%s/tasks - group not found", group_id)
        raise HTTPException(status_code=404, detail=GROUP_NOT_FOUND)

    return await task_crud.get_tasks_by_group(db, group_id=group_id, user_id=current_user.id)

@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: int,
    group_update: GroupUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("PUT /%s - updating group", group_id)
    db_group = await group_crud.get_group(db, group_id=group_id, user_id=current_user.id)
    if not db_group:
        logger.warning("PUT /%s - group not found", group_id)
        raise HTTPException(status_code=404, detail=GROUP_NOT_FOUND)

    update_data = group_update.model_dump(exclude_unset=True)
    if not update_data:
        logger.warning("PUT /%s - no fields to update", group_id)
        raise HTTPException(status_code=400, detail=NO_FIELDS_TO_UPDATE)

    await group_crud.update_group(db, db_group=db_group, group_in=group_update)

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type="GROUP",
        target_id=group_id,
        details=f"Updated group fields: {', '.join(update_data.keys())}",
    )
    await db.commit()
    await db.refresh(db_group)

    logger.info("PUT /%s - group updated", group_id)
    return db_group

@router.delete("/{group_id}")
async def delete_group(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("DELETE /%s - deleting group", group_id)
    db_group = await group_crud.get_group(db, group_id=group_id, user_id=current_user.id)
    if not db_group:
        logger.warning("DELETE /%s - group not found", group_id)
        raise HTTPException(status_code=404, detail=GROUP_NOT_FOUND)

    await group_crud.delete_group(db, db_group=db_group)

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.DELETE,
        target_type="GROUP",
        target_id=group_id,
        details=f"Deleted group: {db_group.name}",
    )
    await db.commit()

    logger.info("DELETE /%s - group deleted", group_id)
    return {"message": "Group deleted successfully"}
