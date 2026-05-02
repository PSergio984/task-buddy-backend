import pytest

from app import security


def test_password_hash():
    password = "my_password"
    assert security.verify_password(password, security.get_password_hash(password))


@pytest.mark.anyio
async def test_get_user(registered_user: dict):
    user = await security.get_user(registered_user["email"])
    assert user["email"] == registered_user["email"]


@pytest.mark.anyio
async def test_get_user_not_found(registered_user: dict):
    user = await security.get_user("nonexistent@example.com")
    assert user is None
