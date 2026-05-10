from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.schemas.project import ProjectCreateRequest, ProjectUpdateRequest


async def get_projects(db: AsyncSession, user_id: int) -> list[Project]:
    query = select(Project).where(Project.user_id == user_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_project(db: AsyncSession, project_id: int, user_id: int) -> Optional[Project]:
    query = select(Project).where(Project.id == project_id, Project.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_project(db: AsyncSession, user_id: int, project_in: ProjectCreateRequest) -> Project:
    db_project = Project(
        **project_in.model_dump(),
        user_id=user_id,
    )
    db.add(db_project)
    await db.flush()
    return db_project


async def update_project(db: AsyncSession, db_project: Project, project_in: ProjectUpdateRequest) -> Project:
    update_data = project_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_project, field, value)
    db.add(db_project)
    await db.flush()
    return db_project


async def delete_project(db: AsyncSession, db_project: Project) -> None:
    await db.delete(db_project)
