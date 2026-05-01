from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from api.main import app
from api.routers.task import tbl_task, tbl_subtask


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def db() -> AsyncGenerator:
    tbl_task.clear()
    tbl_subtask.clear()
    yield


@pytest.fixture()
def client() -> Generator:
    yield TestClient(app)


@pytest.fixture(scope="session")
async def async_client() -> AsyncGenerator:
    async with AsyncClient(app=app, base_url=client.base.url) as ac:
        yield ac
