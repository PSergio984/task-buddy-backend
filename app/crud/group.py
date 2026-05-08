from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import Group
from app.schemas.group import GroupCreateRequest, GroupUpdateRequest


async def get_groups(db: AsyncSession, user_id: int) -> list[Group]:
    query = select(Group).where(Group.user_id == user_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_group(db: AsyncSession, group_id: int, user_id: int) -> Optional[Group]:
    query = select(Group).where(Group.id == group_id, Group.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_group(db: AsyncSession, user_id: int, group_in: GroupCreateRequest) -> Group:
    db_group = Group(
        **group_in.model_dump(),
        user_id=user_id,
    )
    db.add(db_group)
    await db.flush()
    return db_group


async def update_group(db: AsyncSession, db_group: Group, group_in: GroupUpdateRequest) -> Group:
    update_data = group_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_group, field, value)
    db.add(db_group)
    await db.flush()
    return db_group


async def delete_group(db: AsyncSession, db_group: Group) -> None:
    await db.delete(db_group)
