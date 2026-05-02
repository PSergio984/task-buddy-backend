import logging
import datetime

from typing import Annotated
from passlib.hash import argon2
from jose import jwt, ExpiredSignatureError, JWTError
from app.database import database, tbl_user
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer

from app.config import config, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES


logger = logging.getLogger(__name__)

pwd_context = argon2.using(rounds=10)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/users/token")

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def access_token_expire_time() -> int:
    return ACCESS_TOKEN_EXPIRE_MINUTES


def _get_secret_key() -> str:
    if SECRET_KEY:
        return SECRET_KEY
    raise RuntimeError("SECRET_KEY is not set. Set SECRET_KEY (or PROD_SECRET_KEY in production).")


def create_access_token(email: str) -> str:
    logger.debug("Creating access token for email=%s", email)
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=access_token_expire_time()
    )
    jwt_payload = {"sub": email, "exp": expire}
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


async def authenticate_user(email: str, password: str):
    user = await get_user(email)
    if not user:
        raise credentials_exception
    if not verify_password(password, user.password):
        raise credentials_exception
    return user


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except ExpiredSignatureError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except JWTError as e:
        logger.debug("JWT decode error: %s", str(e))
        raise credentials_exception from e

    user = await get_user(email=email)
    if user is None:
        raise credentials_exception

    return user
