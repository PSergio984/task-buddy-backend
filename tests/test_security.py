import pytest
import datetime

from jose import jwt
from app import security


def test_get_subject_for_token_type_valid_access_token():
    email = "test@example.com"
    token = security.create_access_token(email)
    subject = security.get_subject_for_token_type(token, expected_type="access")
    assert subject == email


def test_get_subject_for_token_type_valid_confirm_token():
    email = "test@example.com"
    token = security.create_confirm_token(email)
    subject = security.get_subject_for_token_type(token, expected_type="confirm")
    assert subject == email


def test_get_subject_for_token_type_expired(monkeypatch):
    monkeypatch.setattr(security, "access_token_expire_time", lambda: -1)
    email = "test@example.com"
    token = security.create_access_token(email)
    with pytest.raises(security.HTTPException) as exc_info:
        security.get_subject_for_token_type(token, expected_type="access")
    assert "Token has expired" in exc_info.value.detail


def test_get_subject_for_token_type_invalid_token():
    token = "invalid_token"
    with pytest.raises(security.HTTPException) as exc_info:
        security.get_subject_for_token_type(token, expected_type="access")
    assert "Invalid token" in exc_info.value.detail


def test_get_subject_for_token_type_wrong_type():
    email = "test@example.com"
    token = security.create_access_token(email)
    with pytest.raises(security.HTTPException) as exc_info:
        security.get_subject_for_token_type(token, expected_type="confirm")
    assert "Token has incorrect type, expected 'confirm'" in exc_info.value.detail


def test_get_subject_for_token_type_missing_subject():
    # Create a token with missing 'sub' field
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=30)
    jwt_payload = {"exp": expire, "type": "access"}
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
    token = security.create_access_token("123")

    assert {"sub": "123", "type": "access"}.items() <= jwt.decode(
        token, key=security.SECRET_KEY, algorithms=[security.ALGORITHM]
    ).items()


def test_create_confirmation_token():
    token = security.create_confirm_token("123")

    assert {"sub": "123", "type": "confirm"}.items() <= jwt.decode(
        token, key=security.SECRET_KEY, algorithms=[security.ALGORITHM]
    ).items()


@pytest.mark.anyio
async def test_get_user(registered_user: dict):
    user = await security.get_user(registered_user["email"])
    assert user["email"] == registered_user["email"]


@pytest.mark.anyio
async def test_get_user_not_found(registered_user: dict):
    user = await security.get_user("nonexistent@example.com")
    assert user is None


@pytest.mark.anyio
async def test_authenticate_user(confirmed_user: dict):
    user = await security.authenticate_user(confirmed_user["email"], confirmed_user["password"])
    assert user is not None
    assert user["email"] == confirmed_user["email"]


@pytest.mark.anyio
async def test_authenticate_user_not_found():
    with pytest.raises(security.HTTPException):
        await security.authenticate_user("nonexistent@example.com", "wrong_password")


@pytest.mark.anyio
async def test_authenticate_user_wrong_password(registered_user: dict):
    with pytest.raises(security.HTTPException):
        await security.authenticate_user(registered_user["email"], "wrong_password")


@pytest.mark.anyio
async def test_get_current_user(registered_user: dict):
    token = security.create_access_token(registered_user["email"])
    user = await security.get_current_user(token)
    assert user is not None
    assert user["email"] == registered_user["email"]


@pytest.mark.anyio
async def test_get_current_user_invalid_token():
    with pytest.raises(security.HTTPException):
        await security.get_current_user("invalid_token")


@pytest.mark.anyio
async def test_get_current_user_wrong_type_token(registered_user: dict):
    token = security.create_confirm_token(registered_user["email"])

    with pytest.raises(security.HTTPException):
        await security.get_current_user(token)
