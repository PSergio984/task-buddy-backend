import logging

from passlib.hash import argon2

from app.database import database, tbl_user

logger = logging.getLogger(__name__)

pwd_context = argon2.using(rounds=10)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


async def get_user(email: str):
    logger.debug("Fetching user with email=%s", email)
    query = tbl_user.select().where(tbl_user.c.email == email)
    user = await database.fetch_one(query)
    if user:
        return user
