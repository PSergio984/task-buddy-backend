import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import project as project_crud
from app.crud import task as task_crud
from app.dependencies import get_db
from app.internal.audit import log_action
from app.models.user import User
from app.schemas.enums import AuditAction
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest
from app.schemas.task import TaskCreateResponse
from app.security import get_current_user

logger = logging.getLogger(__name__)

# Error Messages
PROJECT_NOT_FOUND = "Project not found"
NO_FIELDS_TO_UPDATE = "No fields to update"

router = APIRouter(
    tags=["projects"],
    responses={
        404: {"description": PROJECT_NOT_FOUND},
        400: {"description": "Bad request"},
    },
)

@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("GET / - listing projects for user_id=%s", current_user.id)
    return await project_crud.get_projects(db, user_id=current_user.id)

@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    project_in: ProjectCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("POST / - creating project name=%s", project_in.name)

    db_project = await project_crud.create_project(db, user_id=current_user.id, project_in=project_in)

    await db.flush()
    await db.refresh(db_project)

    from sqlalchemy.exc import IntegrityError
    try:
        await log_action(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CREATE,
            target_type="PROJECT",
            target_id=db_project.id,
            details=f"Created project: {db_project.name}",
        )
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        logger.warning("Integrity error creating project: %s", str(e))
        raise HTTPException(status_code=400, detail="Project with this name already exists") from e

    logger.info("POST / - created project id=%s", db_project.id)
    return db_project

@router.get("/{project_id}", response_model=ProjectResponse, responses={404: {"description": PROJECT_NOT_FOUND}})
async def get_project(
    project_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("GET /%s - getting project", project_id)
    db_project = await project_crud.get_project(db, project_id=project_id, user_id=current_user.id)
    if not db_project:
        logger.warning("GET /%s - project not found", project_id)
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND)

    logger.info("GET /%s - project found", project_id)
    return db_project

@router.get("/{project_id}/tasks", response_model=list[TaskCreateResponse], responses={404: {"description": PROJECT_NOT_FOUND}})
async def list_project_tasks(
    project_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("GET /%s/tasks - listing tasks in project", project_id)

    db_project = await project_crud.get_project(db, project_id=project_id, user_id=current_user.id)
    if not db_project:
        logger.warning("GET /%s/tasks - project not found", project_id)
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND)

    tasks = await task_crud.get_tasks_by_project(db, project_id=project_id, user_id=current_user.id)
    return tasks

@router.put("/{project_id}", response_model=ProjectResponse, responses={404: {"description": PROJECT_NOT_FOUND}, 400: {"description": NO_FIELDS_TO_UPDATE}})
async def update_project(
    project_id: int,
    project_update: ProjectUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("PUT /%s - updating project", project_id)
    db_project = await project_crud.get_project(db, project_id=project_id, user_id=current_user.id)
    if not db_project:
        logger.warning("PUT /%s - project not found", project_id)
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND)

    update_data = project_update.model_dump(exclude_unset=True)
    if not update_data:
        logger.warning("PUT /%s - no fields to update", project_id)
        raise HTTPException(status_code=400, detail=NO_FIELDS_TO_UPDATE)

    await project_crud.update_project(db, db_project=db_project, project_in=project_update)

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type="PROJECT",
        target_id=project_id,
        details=f"Updated project '{db_project.name}': {', '.join(update_data.keys())}",
    )
    await db.commit()
    await db.refresh(db_project)

    logger.info("PUT /%s - project updated", project_id)
    return db_project

@router.delete("/{project_id}", responses={404: {"description": PROJECT_NOT_FOUND}})
async def delete_project(
    project_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info("DELETE /%s - deleting project", project_id)
    db_project = await project_crud.get_project(db, project_id=project_id, user_id=current_user.id)
    if not db_project:
        logger.warning("DELETE /%s - project not found", project_id)
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND)

    await project_crud.delete_project(db, db_project=db_project)

    await log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.DELETE,
        target_type="PROJECT",
        target_id=project_id,
        details=f"Deleted project: {db_project.name}",
    )
    await db.commit()

    logger.info("DELETE /%s - project deleted", project_id)
    return {"message": "Project deleted successfully"}
