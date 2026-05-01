import pytest
from httpx import AsyncClient


async def create_task(body: dict, client: AsyncClient) -> dict:
    response = await client.post("/api/v1/tasks/", json=body)
    return response.json()


async def create_subtask(body: str, post_id: int, client: AsyncClient) -> dict:

    response = await client.post("/api/v1/tasks/subtask", json={"title": body, "task_id": post_id})
    return response.json()


@pytest.fixture()
async def created_task(async_client: AsyncClient) -> dict:
    return await create_task({"title": "Test Task"}, async_client)


@pytest.fixture()
async def created_subtask(created_task: dict, async_client: AsyncClient) -> dict:
    return await create_subtask("Test SubTask", created_task["id"], async_client)


@pytest.mark.anyio
async def test_create_task(async_client: AsyncClient):
    body = {"title": "Test Task"}

    response = await async_client.post("/api/v1/tasks/", json=body)

    assert response.status_code == 201
    assert {"id": 1, "title": body["title"]}.items() <= response.json().items()


@pytest.mark.anyio
async def test_create_empty_task(async_client: AsyncClient):

    response = await async_client.post("/api/v1/tasks/", json={})

    assert response.status_code == 422


@pytest.mark.anyio
async def test_get_all_tasks(async_client: AsyncClient, created_task: dict):
    response = await async_client.get("/api/v1/tasks/")

    assert response.status_code == 200
    assert response.json() == [created_task]


@pytest.mark.anyio
async def test_create_subtask(async_client: AsyncClient, created_task: dict):
    body = {"title": "Test SubTask", "task_id": created_task["id"]}

    response = await async_client.post("/api/v1/tasks/subtask", json=body)

    assert response.status_code == 201
    assert {
        "id": 1,
        "title": body["title"],
        "task_id": body["task_id"],
    }.items() <= response.json().items()


@pytest.mark.anyio
async def test_get_subtasks_on_task(
    async_client: AsyncClient, created_task: dict, created_subtask: dict
):
    response = await async_client.get(f"/api/v1/tasks/{created_task['id']}/subtask")

    assert response.status_code == 200
    assert response.json() == [created_subtask]


@pytest.mark.anyio
async def test_get_subtasks_on_task_empty(async_client: AsyncClient, created_task: dict):
    response = await async_client.get(f"/api/v1/tasks/{created_task['id']}/subtask")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_get_task_with_subtasks(
    async_client: AsyncClient, created_task: dict, created_subtask: dict
):
    response = await async_client.get(f"/api/v1/tasks/{created_task['id']}/subtasks")

    assert response.status_code == 200
    assert response.json() == {
        "task": created_task,
        "subtasks": [created_subtask],
    }


@pytest.mark.anyio
async def test_get_missing_task_with_subtasks(
    async_client: AsyncClient, created_subtask: dict, created_task: dict
):
    response = await async_client.get("/api/v1/tasks/999/subtasks")

    assert response.status_code == 404
