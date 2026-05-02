import logging
import sqlite3

import sqlalchemy.exc
from fastapi import APIRouter, HTTPException, status
from app.models.user import UserIn
from app.security import get_password_hash, authenticate_user, create_access_token, get_user
from app.database import database, tbl_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/register", status_code=201)
async def register_user(user: UserIn):
    hashed_password = get_password_hash(user.password)
    query = tbl_user.insert().values(
        email=user.email, password=hashed_password, username=user.username
    )

    logger.debug("Attempting to register user with email: %s", user.email)
    try:
        await database.execute(query)
    except (sqlalchemy.exc.IntegrityError, sqlite3.IntegrityError) as e:
        logger.warning("Registration failed: email %s already registered", user.email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        ) from e


@router.post("/token")
async def login(user: UserIn):
    user = await authenticate_user(user.email, user.password)
    access_token = create_access_token(user.email)
    return {"access_token": access_token, "token_type": "bearer"}
