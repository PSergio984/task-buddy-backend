from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import database


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def db() -> AsyncGenerator:
    await database.connect()
    yield
    await database.disconnect()


@pytest.fixture()
def client() -> Generator:
    yield TestClient(app)


@pytest.fixture(scope="session")
async def async_client() -> AsyncGenerator:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http:127.0.0.1/") as ac:
        yield ac
