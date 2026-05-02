from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import database, tbl_user, tbl_task, tbl_subtask


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture()
async def db(autouse=True) -> AsyncGenerator:
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
    await async_client.post("/api/v1/register", json=user_data)
    query = tbl_user.select().where(tbl_user.c.email == user_data["email"])
    user = await database.fetch_one(query)
    user_data["id"] = user["id"]
    return user_data
