import datetime
import logging
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    CONFIRM_TOKEN_EXPIRE_MINUTES,
    RESET_TOKEN_EXPIRE_MINUTES,
    SECRET_KEY,
)
from app.crud.user import get_user_by_email
from app.crud.user import get_user_by_id as crud_get_user_by_id
from app.dependencies import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["argon2", "pbkdf2_sha256"], deprecated="auto")

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


def create_access_token(user_id: int) -> str:
    logger.debug("Creating access token for user_id=%s", user_id)
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=access_token_expire_time()
    )
    jwt_payload = {"sub": str(user_id), "exp": expire, "type": "access"}
    jwt_encoded = jwt.encode(jwt_payload, SECRET_KEY, algorithm=ALGORITHM)
    return jwt_encoded


def create_confirm_token(user_id: int) -> str:
    logger.debug("Creating confirmation token for user_id=%s", user_id)
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=confirm_token_expire_time()
    )
    jwt_payload = {"sub": str(user_id), "exp": expire, "type": "confirm"}
    jwt_encoded = jwt.encode(jwt_payload, SECRET_KEY, algorithm=ALGORITHM)
    return jwt_encoded


def create_reset_token(user_id: int) -> str:
    logger.debug("Creating reset token for user_id=%s", user_id)
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=reset_token_expire_time()
    )
    jwt_payload = {"sub": str(user_id), "exp": expire, "type": "reset"}
    jwt_encoded = jwt.encode(jwt_payload, SECRET_KEY, algorithm=ALGORITHM)
    return jwt_encoded


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_subject_for_token_type(
    token: str, expected_type: Literal["access", "confirm", "reset"]
) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(db, email)
    if not user:
        raise create_credentials_exception("Invalid credentials")
    if not verify_password(password, user.password):
        raise create_credentials_exception("Invalid credentials")

    # Lazy migration to new hashing scheme (Argon2) if needed
    if pwd_context.needs_update(user.password):
        logger.info("Re-hashing password for user_id=%s", user.id)
        user.password = get_password_hash(password)
        # Note: Transaction commit is handled by the caller (router)

    if not user.confirmed:
        raise create_credentials_exception("Invalid credentials")
    return user


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:

    subject = get_subject_for_token_type(token, expected_type="access")
    try:
        user_id = int(subject)
    except ValueError as err:
        raise create_credentials_exception("Invalid user ID in token") from err

    user = await crud_get_user_by_id(db, user_id=user_id)
    if user is None:
        raise create_credentials_exception("Could not find user for this token")

    return user
