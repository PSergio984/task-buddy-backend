"""API endpoints for managing projects."""

import logging
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    RATE_LIMIT_PROJECT_CREATE,
    RATE_LIMIT_PROJECT_DELETE,
    RATE_LIMIT_PROJECT_UPDATE,
    RATE_LIMIT_TASK_GET,
)
from app.crud import project as project_crud
from app.crud import task as task_crud
from app.dependencies import get_db
from app.libs.cache import get_cache_key, get_cached_data, set_cached_data
from app.limiter import limiter
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest
from app.schemas.task import TaskCreateResponse
from app.security import get_confirmed_user, get_redis_client

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
@limiter.limit(RATE_LIMIT_TASK_GET)
async def list_projects(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Project]:
    logger.info("GET / - listing projects for user_id=%s", current_user.id)

    cache_key = get_cache_key("projects_list", current_user.id, limit=limit, offset=offset)
    cached = await get_cached_data(cache_key, list[ProjectResponse])
    if cached is not None:
        return cast(list[Project], cached)

    projects = await project_crud.get_projects(
        db, user_id=current_user.id, limit=limit, offset=offset
    )
    await set_cached_data(cache_key, projects)
    return projects


@router.post("/", response_model=ProjectResponse, status_code=201)
@limiter.limit(RATE_LIMIT_PROJECT_CREATE)
async def create_project(
    project_in: ProjectCreateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Project:
    logger.info("POST / - creating project name=%s", project_in.name)

    try:
        db_project: Project = await project_crud.create_project(
            db, user_id=current_user.id, project_in=project_in
        )
        await db.commit()
        await db.refresh(db_project)
    except ValueError as e:
        await db.rollback()
        logger.warning("Quota limit exceeded: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        await db.rollback()
        logger.warning("Integrity error creating project: %s", str(e))
        raise HTTPException(status_code=400, detail="Project with this name already exists") from e

    logger.info("POST / - created project id=%s", db_project.id)

    # Invalidate cache
    redis = get_redis_client()
    if redis:
        keys = await redis.keys(f"cache:projects_list:{current_user.id}:*")
        if keys:
            await redis.delete(*keys)

    return db_project


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={404: {"description": PROJECT_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_TASK_GET)
async def get_project(
    project_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Project:
    logger.info("GET /%s - getting project", project_id)
    db_project = await project_crud.get_project(db, project_id=project_id, user_id=current_user.id)
    if not db_project:
        logger.warning("GET /%s - project not found", project_id)
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND)

    logger.info("GET /%s - project found", project_id)
    return db_project


@router.get(
    "/{project_id}/tasks",
    response_model=list[TaskCreateResponse],
    responses={404: {"description": PROJECT_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_TASK_GET)
async def list_project_tasks(
    project_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Task]:
    logger.info("GET /%s/tasks - listing tasks in project", project_id)

    db_project = await project_crud.get_project(db, project_id=project_id, user_id=current_user.id)
    if not db_project:
        logger.warning("GET /%s/tasks - project not found", project_id)
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND)

    tasks = await task_crud.get_tasks_by_project(db, project_id=project_id, user_id=current_user.id)
    return tasks


@router.put(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={
        404: {"description": PROJECT_NOT_FOUND},
        400: {"description": NO_FIELDS_TO_UPDATE},
    },
)
@limiter.limit(RATE_LIMIT_PROJECT_UPDATE)
async def update_project(
    project_id: int,
    project_update: ProjectUpdateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Project:
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
    await db.commit()
    await db.refresh(db_project)

    logger.info("PUT /%s - project updated", project_id)

    # Invalidate cache
    redis = get_redis_client()
    if redis:
        keys = await redis.keys(f"cache:projects_list:{current_user.id}:*")
        if keys:
            await redis.delete(*keys)

    return db_project


@router.delete("/{project_id}", responses={404: {"description": PROJECT_NOT_FOUND}})
@limiter.limit(RATE_LIMIT_PROJECT_DELETE)
async def delete_project(
    project_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    delete_tasks: bool = Query(False, description="Delete all associated tasks if true"),
) -> dict[str, str]:
    logger.info("DELETE /%s - deleting project (delete_tasks=%s)", project_id, delete_tasks)
    db_project = await project_crud.get_project(db, project_id=project_id, user_id=current_user.id)
    if not db_project:
        logger.warning("DELETE /%s - project not found", project_id)
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND)

    await project_crud.delete_project(
        db, db_project=db_project, user_id=current_user.id, delete_tasks=delete_tasks
    )
    await db.commit()

    logger.info("DELETE /%s - project deleted", project_id)

    # Invalidate cache
    redis = get_redis_client()
    if redis:
        keys = await redis.keys(f"cache:projects_list:{current_user.id}:*")
        if keys:
            await redis.delete(*keys)

    return {"message": "Project deleted successfully"}


@router.post("/reorder")
@limiter.limit(RATE_LIMIT_PROJECT_UPDATE)
async def reorder_projects(
    ordered_ids: list[int],
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    logger.info("POST /reorder - reordering projects for user_id=%s", current_user.id)
    await project_crud.reorder_projects(db, user_id=current_user.id, ordered_ids=ordered_ids)
    await db.commit()

    # Invalidate cache
    redis = get_redis_client()
    if redis:
        keys = await redis.keys(f"cache:projects_list:{current_user.id}:*")
        if keys:
            await redis.delete(*keys)

    return {"message": "Projects reordered successfully"}
