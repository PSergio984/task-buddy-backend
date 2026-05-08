import datetime

import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from app.crud.user import get_user_by_id
from app import security


def test_get_subject_for_token_type_valid_access_token():
    user_id = 123
    token = security.create_access_token(user_id)
    subject = security.get_subject_for_token_type(token, expected_type="access")
    assert subject == str(user_id)


def test_get_subject_for_token_type_valid_confirm_token():
    user_id = 123
    token = security.create_confirm_token(user_id)
    subject = security.get_subject_for_token_type(token, expected_type="confirm")
    assert subject == str(user_id)


def test_get_subject_for_token_type_expired(monkeypatch):
    monkeypatch.setattr(security, "access_token_expire_time", lambda: -1)
    user_id = 123
    token = security.create_access_token(user_id)
    with pytest.raises(security.HTTPException) as exc_info:
        security.get_subject_for_token_type(token, expected_type="access")
    assert "Token has expired" in exc_info.value.detail


def test_get_subject_for_token_type_invalid_token():
    token = "invalid_token"
    with pytest.raises(security.HTTPException) as exc_info:
        security.get_subject_for_token_type(token, expected_type="access")
    assert "Invalid token" in exc_info.value.detail


def test_get_subject_for_token_type_wrong_type():
    user_id = 123
    token = security.create_access_token(user_id)
    with pytest.raises(security.HTTPException) as exc_info:
        security.get_subject_for_token_type(token, expected_type="confirm")
    assert "Token has incorrect type, expected 'confirm'" in exc_info.value.detail


def test_get_subject_for_token_type_missing_subject():
    # Create a token with missing 'sub' field
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=30)
    jwt_payload = {"exp": expire, "type": "access"}
    assert security.SECRET_KEY is not None
    token = jwt.encode(jwt_payload, security.SECRET_KEY, algorithm=security.ALGORITHM)

    with pytest.raises(security.HTTPException) as exc_info:
        security.get_subject_for_token_type(token, expected_type="access")
    assert "Token is missing subject field" in exc_info.value.detail


def test_password_hash():
    password = "my_password"
    assert security.verify_password(password, security.get_password_hash(password))


def test_access_token_expire_minutes():
    assert security.access_token_expire_time() == 30


def test_confirm_token_expire_minutes():
    assert security.confirm_token_expire_time() == 1440


def test_create_access_token():
    token = security.create_access_token(123)

    assert security.SECRET_KEY is not None
    assert {"sub": "123", "type": "access"}.items() <= jwt.decode(
        token, key=security.SECRET_KEY, algorithms=[security.ALGORITHM]
    ).items()


def test_create_confirmation_token():
    token = security.create_confirm_token(123)

    assert security.SECRET_KEY is not None
    assert {"sub": "123", "type": "confirm"}.items() <= jwt.decode(
        token, key=security.SECRET_KEY, algorithms=[security.ALGORITHM]
    ).items()


@pytest.mark.anyio
async def test_get_user(db: AsyncSession, registered_user: dict):
    from app.crud.user import get_user_by_email

    user = await get_user_by_email(db, registered_user["email"])
    assert user is not None
    assert user.email == registered_user["email"]


@pytest.mark.anyio
async def test_get_user_not_found(db: AsyncSession):
    from app.crud.user import get_user_by_email

    user = await get_user_by_email(db, "nonexistent@example.com")
    assert user is None


@pytest.mark.anyio
async def test_authenticate_user(db: AsyncSession, confirmed_user: dict):
    user = await security.authenticate_user(db, confirmed_user["email"], confirmed_user["password"])
    assert user is not None
    assert user.email == confirmed_user["email"]


@pytest.mark.anyio
async def test_authenticate_user_not_found(db: AsyncSession):
    with pytest.raises(security.HTTPException):
        await security.authenticate_user(db, "nonexistent@example.com", "wrong_password")


@pytest.mark.anyio
async def test_authenticate_user_wrong_password(db: AsyncSession, registered_user: dict):
    with pytest.raises(security.HTTPException):
        await security.authenticate_user(db, registered_user["email"], "wrong_password")


@pytest.mark.anyio
async def test_get_current_user(db: AsyncSession, registered_user: dict):
    token = security.create_access_token(registered_user["id"])
    user = await security.get_current_user(token, db)
    assert user is not None
    assert user.email == registered_user["email"]


@pytest.mark.anyio
async def test_get_current_user_invalid_token(db: AsyncSession):
    with pytest.raises(security.HTTPException):
        await security.get_current_user("invalid_token", db)


@pytest.mark.anyio
async def test_get_current_user_wrong_type_token(db: AsyncSession, registered_user: dict):
    token = security.create_confirm_token(registered_user["id"])
    with pytest.raises(security.HTTPException):
        await security.get_current_user(token, db)


@pytest.mark.anyio
async def test_authenticate_user_lazy_migration(db: AsyncSession, confirmed_user: dict):
    from passlib.context import CryptContext

    # Manually set a legacy pbkdf2_sha256 hash for the user
    legacy_ctx = CryptContext(schemes=["pbkdf2_sha256"])
    legacy_hash = legacy_ctx.hash(confirmed_user["password"])
    assert legacy_hash.startswith("$pbkdf2-sha256$")

    user = await get_user_by_id(db, confirmed_user["id"])
    assert user is not None, f"User {confirmed_user['email']} not found in database"
    user.password = legacy_hash
    await db.commit()
    await db.refresh(user)

    # Authenticate - should trigger re-hash
    authenticated_user = await security.authenticate_user(
        db, confirmed_user["email"], confirmed_user["password"]
    )

    # Verify it's re-hashed to Argon2
    assert authenticated_user.password.startswith("$argon2id$")
    assert security.verify_password(confirmed_user["password"], authenticated_user.password)
