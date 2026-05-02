from collections.abc import AsyncGenerator, Generator
import logging

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import database, tbl_user, tbl_task, tbl_subtask


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def db() -> AsyncGenerator:
    await database.connect()
    # Clear task tables before each test
    await database.execute(tbl_subtask.delete())
    await database.execute(tbl_task.delete())
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


@pytest.fixture(scope="session")
async def registered_user(async_client: AsyncClient) -> dict:
    user_data = {
        "username": "testuser",
        "email": "testuser@example.com",
        "password": "testpassword",
    }
    response = await async_client.post("/api/v1/users/register", json=user_data)

    # Handle existing user (from previous test runs)
    if response.status_code == 400 and "already registered" in response.json().get("detail", ""):
        logger = logging.getLogger(__name__)
        logger.debug(f"User {user_data['email']} already exists, fetching from database")
    else:
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
