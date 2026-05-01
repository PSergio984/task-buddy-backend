import pytest
from httpx import AsyncClient


async def create_task(body: dict, client: AsyncClient) -> dict:
    response = await client.post("/api/v1/tasks/", json=body)
    return response.json()


@pytest.fixture()
async def created_task(async_client: AsyncClient) -> dict:
    return await create_task({"title": "Test Task"}, async_client)


@pytest.mark.anyio
async def test_create_task(async_client: AsyncClient):
    body = {"title": "Test Task"}

    response = await async_client.post("/api/v1/tasks/", json=body)

    assert response.status_code == 201
    assert {"id": "3", "title": body["title"]}.items() <= response.json().items()


@pytest.mark.anyio
async def test_create_empty_task(async_client: AsyncClient):

    response = await async_client.post("/api/v1/tasks/", json={})

    assert response.status_code == 422


@pytest.mark.anyio
async def test_get_all_tasks(async_client: AsyncClient, created_task: dict):
    response = await async_client.get("/api/v1/tasks/")

    assert response.status_code == 200
    assert response.json() == [created_task]
