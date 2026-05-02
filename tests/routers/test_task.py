import pytest
from httpx import AsyncClient
from app import security


async def create_task(body: dict, client: AsyncClient, logged_in_token: str) -> dict:
    response = await client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    return response.json()


async def create_subtask(
    body: str, post_id: int, client: AsyncClient, logged_in_token: str
) -> dict:

    response = await client.post(
        "/api/v1/tasks/subtask",
        json={"title": body, "task_id": post_id},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    return response.json()


@pytest.fixture()
async def created_task(db, async_client: AsyncClient, logged_in_token: str) -> dict:
    return await create_task({"title": "Test Task"}, async_client, logged_in_token)


@pytest.fixture()
async def created_subtask(
    created_task: dict, async_client: AsyncClient, logged_in_token: str
) -> dict:
    return await create_subtask("Test SubTask", created_task["id"], async_client, logged_in_token)


@pytest.mark.anyio
async def test_create_task(
    db, async_client: AsyncClient, logged_in_token: str, registered_user: dict
):
    body = {"title": "Test Task"}

    response = await async_client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 201
    assert {
        "id": 1,
        "title": body["title"],
        "user_id": registered_user["id"],
    }.items() <= response.json().items()


@pytest.mark.anyio
async def test_create_empty_task(db, async_client: AsyncClient, logged_in_token: str):

    response = await async_client.post(
        "/api/v1/tasks/", json={}, headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_task_expired_token(
    db, async_client: AsyncClient, registered_user: dict, monkeypatch
):
    monkeypatch.setattr(security, "access_token_expire_time", lambda: -1)
    token = security.create_access_token(registered_user["email"])
    response = await async_client.post(
        "/api/v1/tasks/", json={"title": "Test Task"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert (
        "Token has expired" in response.json()["detail"]
        or "Could not validate credentials" in response.json()["detail"]
    )


@pytest.mark.anyio
async def test_get_all_tasks(async_client: AsyncClient, created_task: dict):
    response = await async_client.get("/api/v1/tasks/")

    assert response.status_code == 200
    assert response.json() == [created_task]


@pytest.mark.anyio
async def test_create_subtask(
    async_client: AsyncClient,
    created_task: dict,
    logged_in_token: str,
    registered_user: dict,
):
    body = {"title": "Test SubTask", "task_id": created_task["id"]}

    response = await async_client.post(
        "/api/v1/tasks/subtask", json=body, headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 201
    assert {
        "id": 1,
        "title": body["title"],
        "task_id": body["task_id"],
        "user_id": registered_user["id"],
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
