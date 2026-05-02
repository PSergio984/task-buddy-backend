import logging
import sqlite3

import sqlalchemy.exc
from fastapi import APIRouter, HTTPException, status
from app.models.user import UserIn, Login
from app.security import get_password_hash, authenticate_user, create_access_token, get_user
from app.database import database, tbl_user

logger = logging.getLogger(__name__)

# Constants to avoid duplicated literals and improve OpenAPI docs
ROUTER_TAG = "users"
REGISTER_PATH = "/register"
TOKEN_PATH = "/token"
EMAIL_ALREADY_REGISTERED = "Email already registered"
AUTH_CREDENTIALS_ERROR = "Could not validate credentials"

router = APIRouter(tags=[ROUTER_TAG])


@router.post(
    REGISTER_PATH, status_code=201, responses={400: {"description": EMAIL_ALREADY_REGISTERED}}
)
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
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=EMAIL_ALREADY_REGISTERED,
        ) from e


@router.post(TOKEN_PATH, responses={401: {"description": AUTH_CREDENTIALS_ERROR}})
async def login(credentials: Login):
    auth_user = await authenticate_user(credentials.email, credentials.password)
    access_token = create_access_token(auth_user["email"])
    return {"access_token": access_token, "token_type": "bearer"}
