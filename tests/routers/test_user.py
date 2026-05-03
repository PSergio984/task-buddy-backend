import pytest
from httpx import AsyncClient


async def register_user(
    async_client: AsyncClient, username: str, email: str, password: str
) -> dict:
    return await async_client.post(
        "/api/v1/users/register",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )


@pytest.mark.anyio
async def test_register_user(db, async_client: AsyncClient):
    response = await register_user(async_client, "newuser", "example@email.net", "newpassword")
    assert response.status_code == 201
    assert "User Created" in response.json()["detail"]


@pytest.mark.anyio
async def test_register_user_duplicate_email(async_client: AsyncClient, registered_user: dict):
    response = await register_user(
        async_client, registered_user["username"], registered_user["email"], "anotherpassword"
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.anyio
async def test_login_user_not_exists(db, async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": "test@example.net", "password": "any"},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_login_user(async_client: AsyncClient, registered_user: dict):
    response = await async_client.post(
        "/api/v1/users/token",
        data={
            "username": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
