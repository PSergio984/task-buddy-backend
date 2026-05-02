import pytest
from httpx import AsyncClient


async def register_user(
    async_client: AsyncClient, username: str, email: str, password: str
) -> dict:
    return await async_client.post(
        "/register",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )


@pytest.mark.anyio
async def test_register_user(async_client: AsyncClient):
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
async def test_login_user_not_exists(async_client: AsyncClient):
    response = await async_client.post(
        "/token", json={"email": "test@example.net", "password": "any"}
    )
    assert response.status_code == 401


async def test_login_user(async_client: AsyncClient, registered_user: dict):
    response = await async_client.post(
        "/token", json={"email": registered_user["email"], "password": registered_user["password"]}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
