import datetime
import hashlib
import logging
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    CONFIRM_TOKEN_EXPIRE_MINUTES,
    REDIS_URL,
    RESET_TOKEN_EXPIRE_MINUTES,
    SECRET_KEY,
)
from app.crud.user import get_user_by_email
from app.crud.user import get_user_by_id as crud_get_user_by_id
from app.dependencies import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["argon2", "pbkdf2_sha256"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/users/token", auto_error=False)

# Initialize Redis client
redis_client = None
if REDIS_URL:
    try:
        from redis import asyncio as aioredis

        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    except ImportError as e:
        logger.warning("Redis could not be initialized: %s", str(e))


async def get_token(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
) -> str:
    # First check the Authorization header (standard OAuth2)
    if token:
        return token

    # Fallback to HttpOnly cookie
    token = request.cookies.get("access_token")
    if token:
        return token

    raise create_credentials_exception("Not authenticated")


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


async def blacklist_token(token: str, expires_in: int) -> None:
    """Blacklist a JWT token in Redis with a TTL."""
    if redis_client is None:
        logger.error("Redis client is not initialized; cannot blacklist token.")
        return
    try:
        # Store a hash of the token to keep Redis keys short and secure
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        await redis_client.setex(f"blacklist:{token_hash}", expires_in, "true")
        logger.debug("Token blacklisted successfully.")
    except Exception as e:
        logger.error("Failed to blacklist token in Redis: %s", str(e))
        # Failsafe: if we can't blacklist, we should probably know
        raise


async def is_token_blacklisted(token: str) -> bool:
    """Check if a JWT token is present in the Redis blacklist."""
    if redis_client is None:
        logger.warning("Redis client is not initialized; assuming token is not blacklisted.")
        return False
    try:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return await redis_client.exists(f"blacklist:{token_hash}") > 0
    except Exception as e:
        logger.error("Failed to check token blacklist in Redis: %s", str(e))
        # Fail-closed: reject token if security check fails
        raise create_credentials_exception("Token validation unavailable") from e


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
    except JWTError as e:
        if isinstance(e, ExpiredSignatureError):
            raise create_credentials_exception("Token has expired") from e
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
    token: Annotated[str, Depends(get_token)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if await is_token_blacklisted(token):
        raise create_credentials_exception("Token is blacklisted")

    subject = get_subject_for_token_type(token, expected_type="access")
    try:
        user_id = int(subject)
    except ValueError as err:
        raise create_credentials_exception("Invalid user ID in token") from err

    user = await crud_get_user_by_id(db, user_id=user_id)
    if user is None:
        raise create_credentials_exception("Could not find user for this token")

    if not user.confirmed:
        raise create_credentials_exception("Email not confirmed")

    return user
