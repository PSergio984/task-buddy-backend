import logging
import datetime

from typing import Annotated, Literal
from passlib.context import CryptContext
from jose import jwt, ExpiredSignatureError, JWTError
from app.database import database, tbl_user
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer

from app.config import (
    config,
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    CONFIRM_TOKEN_EXPIRE_MINUTES,
    RESET_TOKEN_EXPIRE_MINUTES,
)


logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/users/token")


def create_credentials_exception(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def access_token_expire_time() -> int:
    return ACCESS_TOKEN_EXPIRE_MINUTES


def confirm_token_expire_time() -> int:
    return CONFIRM_TOKEN_EXPIRE_MINUTES


def reset_token_expire_time() -> int:
    return RESET_TOKEN_EXPIRE_MINUTES


def _get_secret_key() -> str:
    if SECRET_KEY:
        return SECRET_KEY
    raise RuntimeError("SECRET_KEY is not set. Set SECRET_KEY (or PROD_SECRET_KEY in production).")


def create_access_token(user_id: int) -> str:
    logger.debug("Creating access token for user_id=%s", user_id)
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=access_token_expire_time()
    )
    jwt_payload = {"sub": str(user_id), "exp": expire, "type": "access"}
    secret = _get_secret_key()
    jwt_encoded = jwt.encode(jwt_payload, secret, algorithm=ALGORITHM)
    return jwt_encoded


def create_confirm_token(user_id: int) -> str:
    logger.debug("Creating confirmation token for user_id=%s", user_id)
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=confirm_token_expire_time()
    )
    jwt_payload = {"sub": str(user_id), "exp": expire, "type": "confirm"}
    secret = _get_secret_key()
    jwt_encoded = jwt.encode(jwt_payload, secret, algorithm=ALGORITHM)
    return jwt_encoded


def create_reset_token(user_id: int) -> str:
    logger.debug("Creating reset token for user_id=%s", user_id)
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=reset_token_expire_time()
    )
    jwt_payload = {"sub": str(user_id), "exp": expire, "type": "reset"}
    secret = _get_secret_key()
    jwt_encoded = jwt.encode(jwt_payload, secret, algorithm=ALGORITHM)
    return jwt_encoded


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


async def get_user_by_id(user_id: int):
    logger.debug("Fetching user with id=%s", user_id)
    query = tbl_user.select().where(tbl_user.c.id == user_id)
    user = await database.fetch_one(query)
    if user:
        return user


def get_subject_for_token_type(
    token: str, expected_type: Literal["access", "confirm", "reset"]
) -> str:
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
    except ExpiredSignatureError as e:
        raise create_credentials_exception("Token has expired") from e

    except JWTError as e:
        logger.debug("JWT decode error: %s", str(e))
        raise create_credentials_exception("Invalid token") from e

    subject = payload.get("sub")
    if subject is None:
        raise create_credentials_exception("Token is missing subject field")
    token_type = payload.get("type")
    if token_type is None or token_type != expected_type:
        logger.debug("Invalid token type: expected '%s', got '%s'", expected_type, token_type)
        raise create_credentials_exception(f"Token has incorrect type, expected '{expected_type}'")

    return subject


async def authenticate_user(email: str, password: str):
    user = await get_user(email)
    if not user:
        raise create_credentials_exception("Invalid credentials")
    if not verify_password(password, user.password):
        raise create_credentials_exception("Invalid credentials")
    if not user.confirmed:
        raise create_credentials_exception("Email not confirmed")
    return user


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):

    subject = get_subject_for_token_type(token, expected_type="access")
    try:
        user_id = int(subject)
    except ValueError:
        raise create_credentials_exception("Invalid user ID in token")

    user = await get_user_by_id(user_id=user_id)
    if user is None:
        raise create_credentials_exception("Could not find user for this token")

    return user
