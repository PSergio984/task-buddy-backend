from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.libs.audit import audit_log
from app.models.project import Project
from app.schemas.enums import AuditAction
from app.schemas.project import ProjectCreateRequest, ProjectUpdateRequest

PROJECT_TARGET_TYPE = "PROJECT"


async def get_projects(db: AsyncSession, user_id: int) -> list[Project]:
    query = select(Project).where(Project.user_id == user_id).order_by(Project.position)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_project(db: AsyncSession, project_id: int, user_id: int) -> Optional[Project]:
    query = select(Project).where(Project.id == project_id, Project.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


@audit_log(action=AuditAction.CREATE, target_type=PROJECT_TARGET_TYPE)
async def create_project(db: AsyncSession, user_id: int, project_in: ProjectCreateRequest) -> Project:
    db_project = Project(
        **project_in.model_dump(),
        user_id=user_id,
    )
    db.add(db_project)
    await db.flush()
    return db_project


@audit_log(
    action=AuditAction.UPDATE,
    target_type=PROJECT_TARGET_TYPE,
    include_diff=True
)
async def update_project(db: AsyncSession, db_project: Project, project_in: ProjectUpdateRequest) -> Project:
    update_data = project_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_project, field, value)
    db.add(db_project)
    await db.flush()
    return db_project


@audit_log(action=AuditAction.DELETE, target_type=PROJECT_TARGET_TYPE)
async def delete_project(db: AsyncSession, db_project: Project, user_id: int | None = None) -> None:
    await db.delete(db_project)


async def reorder_projects(db: AsyncSession, user_id: int, ordered_ids: list[int]) -> None:
    for index, project_id in enumerate(ordered_ids):
        query = select(Project).where(Project.id == project_id, Project.user_id == user_id)
        result = await db.execute(query)
        db_project = result.scalar_one_or_none()
        if db_project:
            db_project.position = index
            db.add(db_project)
    await db.flush()
