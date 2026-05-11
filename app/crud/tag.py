from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.libs.audit import audit_log
from app.models.tag import Tag
from app.models.task import task_tags
from app.schemas.enums import AuditAction
from app.schemas.tag import TagCreate


async def get_user_tags(db: AsyncSession, user_id: int) -> list[Tag]:
    query = select(Tag).where(Tag.user_id == user_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_tag_by_name(db: AsyncSession, user_id: int, name: str) -> Optional[Tag]:
    query = select(Tag).where(Tag.user_id == user_id, Tag.name == name)
    result = await db.execute(query)
    return result.scalar_one_or_none()


@audit_log(action=AuditAction.CREATE, target_type="TAG")
async def create_tag(db: AsyncSession, user_id: int, tag_in: TagCreate) -> Tag:
    db_tag = Tag(
        user_id=user_id,
        name=tag_in.name
    )
    db.add(db_tag)
    await db.flush()
    return db_tag


@audit_log(action=AuditAction.DELETE, target_type="TAG")
async def delete_tag(db: AsyncSession, db_tag: Tag) -> None:
    await db.delete(db_tag)


@audit_log(action=AuditAction.UPDATE, target_type="TASK")
async def attach_tag_to_task(db: AsyncSession, task_id: int, tag_id: int, user_id: int | None = None) -> bool:
    """
    Attaches a tag to a task. Returns True if a new link was created.
    """
    # Check if already exists
    query = select(task_tags).where(
        task_tags.c.task_id == task_id,
        task_tags.c.tag_id == tag_id
    )
    result = await db.execute(query)
    if result.scalar_one_or_none():
        return False

    stmt = task_tags.insert().values(task_id=task_id, tag_id=tag_id)
    await db.execute(stmt)
    return True


@audit_log(action=AuditAction.UPDATE, target_type="TASK")
async def detach_tag_from_task(db: AsyncSession, task_id: int, tag_id: int, user_id: int | None = None) -> None:
    stmt = task_tags.delete().where(
        task_tags.c.task_id == task_id,
        task_tags.c.tag_id == tag_id
    )
    await db.execute(stmt)


async def get_tags_on_task(db: AsyncSession, task_id: int) -> list[Tag]:
    query = select(Tag).join(task_tags, Tag.id == task_tags.c.tag_id).where(task_tags.c.task_id == task_id)
    result = await db.execute(query)
    return list(result.scalars().all())
