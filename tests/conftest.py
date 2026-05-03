from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import (
    database,
    engine,
    metadata,
    tbl_user,
    tbl_task,
    tbl_subtask,
    tbl_tag,
    tbl_task_tags,
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture()
async def db() -> AsyncGenerator:
    metadata.drop_all(engine)
    metadata.create_all(engine)
    await database.connect()
    # Clear child tables before parents to respect FK constraints.
    await database.execute(tbl_task_tags.delete())
    await database.execute(tbl_tag.delete())
    await database.execute(tbl_subtask.delete())
    await database.execute(tbl_task.delete())
    await database.execute(tbl_user.delete())
    yield
    await database.disconnect()


@pytest.fixture()
def client() -> Generator:
    yield TestClient(app)


@pytest.fixture(scope="session")
async def async_client() -> AsyncGenerator:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver/") as ac:
        yield ac


@pytest.fixture()
async def registered_user(db, async_client: AsyncClient) -> dict:
    user_data = {
        "username": "testuser",
        "email": "testuser@example.com",
        "password": "testpassword",
    }
    response = await async_client.post("/api/v1/users/register", json=user_data)

    assert response.status_code == 201, (
        f"Registration failed with status {response.status_code}: {response.json()}"
    )

    query = tbl_user.select().where(tbl_user.c.email == user_data["email"])
    user = await database.fetch_one(query)
    assert user is not None, (
        f"User not found in database after registration for email: {user_data['email']}"
    )

    user_data["id"] = user["id"]
    return user_data


@pytest.fixture()
async def logged_in_token(async_client: AsyncClient, registered_user: dict) -> str:
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": registered_user["email"], "password": registered_user["password"]},
    )
    assert response.status_code == 200, (
        f"Login failed with status {response.status_code}: {response.json()}"
    )

    payload = response.json()
    token = payload.get("access_token")
    assert isinstance(token, str) and token, (
        f"Login response did not include a valid access_token: {payload}"
    )
    return token
