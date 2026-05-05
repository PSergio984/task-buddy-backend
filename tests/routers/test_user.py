import pytest
from httpx import AsyncClient
from fastapi import Request


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
async def test_confirm_user(db, async_client: AsyncClient, mocker):
    spy = mocker.spy(Request, "url_for")

    await register_user(async_client, "testuser", "test@example.net", "1234")
    confirmation_url = str(spy.spy_return)
    response = await async_client.get(confirmation_url)

    assert response.status_code == 200
    assert "Email confirmed" in response.json()["detail"]


@pytest.mark.anyio
async def test_confirm_user_invalid_token(async_client: AsyncClient):
    response = await async_client.get("/api/v1/users/confirm/invalidtoken")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_confirm_user_expired_token(async_client: AsyncClient, mocker, request: Request):
    mocker.patch("app.security.confirm_token_expire_time", return_value=-1)

    spy = mocker.spy(Request, "url_for")
    await register_user(async_client, "testuser2", "test@exaple.net", "1234")
    confirmation_url = str(spy.spy_return)
    response = await async_client.get(confirmation_url)

    assert response.status_code == 401
    assert "Token has expired" in response.json()["detail"]


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
async def test_login_user_not_confirmed(async_client: AsyncClient, registered_user: dict):
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": registered_user["email"], "password": registered_user["password"]},
    )
    assert response.status_code == 401
    assert "Email not confirmed" in response.json()["detail"]


@pytest.mark.anyio
async def test_login_user(async_client: AsyncClient, confirmed_user: dict):
    response = await async_client.post(
        "/api/v1/users/token",
        data={
            "username": confirmed_user["email"],
            "password": confirmed_user["password"],
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
