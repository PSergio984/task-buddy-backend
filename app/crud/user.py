from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserCreateRequest


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, user_in: UserCreateRequest, hashed_password: str) -> User:
    db_user = User(
        username=user_in.username,
        email=user_in.email,
        password=hashed_password,
    )
    db.add(db_user)
    await db.flush()
    return db_user


async def update_user_confirmation(db: AsyncSession, db_user: User, confirmed: bool = True) -> User:
    db_user.confirmed = confirmed
    db_user.confirmation_failed = not confirmed
    db.add(db_user)
    await db.flush()
    return db_user


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    query = select(User).where(User.username == username)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def update_user(db: AsyncSession, db_user: User, update_data: dict) -> User:
    for field, value in update_data.items():
        setattr(db_user, field, value)
    db.add(db_user)
    await db.flush()
    return db_user
