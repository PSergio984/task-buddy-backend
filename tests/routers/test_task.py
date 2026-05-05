import pytest

from httpx import AsyncClient
from app import security


async def create_task(body: dict, client: AsyncClient, logged_in_token: str) -> dict:
    response = await client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    return response.json()


async def create_subtask(
    body: str, task_id: int, client: AsyncClient, logged_in_token: str
) -> dict:

    response = await client.post(
        "/api/v1/tasks/subtask",
        json={"title": body, "task_id": task_id},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    return response.json()


async def create_tag(body: str, task_id: int, client: AsyncClient, logged_in_token: str) -> dict:
    response = await client.post(
        f"/api/v1/tasks/{task_id}/tags",
        json={"name": body},
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


@pytest.fixture()
async def created_tag(created_task: dict, async_client: AsyncClient, logged_in_token: str) -> dict:
    return await create_tag("Important", created_task["id"], async_client, logged_in_token)


@pytest.mark.anyio
async def test_create_task(
    db, async_client: AsyncClient, logged_in_token: str, confirmed_user: dict
):
    body = {"title": "Test Task"}

    response = await async_client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 201
    assert {
        "id": 1,
        "title": body["title"],
        "user_id": confirmed_user["id"],
    }.items() <= response.json().items()


@pytest.mark.anyio
async def test_create_empty_task(db, async_client: AsyncClient, logged_in_token: str):

    response = await async_client.post(
        "/api/v1/tasks/", json={}, headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_task_expired_token(
    db, async_client: AsyncClient, confirmed_user: dict, monkeypatch
):
    monkeypatch.setattr(security, "access_token_expire_time", lambda: -1)
    token = security.create_access_token(confirmed_user["email"])
    response = await async_client.post(
        "/api/v1/tasks/", json={"title": "Test Task"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert (
        "Token has expired" in response.json()["detail"]
        or "Could not validate credentials" in response.json()["detail"]
    )


@pytest.mark.anyio
async def test_get_all_tasks(async_client: AsyncClient, created_task: dict, logged_in_token: str):
    response = await async_client.get(
        "/api/v1/tasks/", headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 200
    assert response.json() == [created_task]


@pytest.mark.anyio
async def test_create_subtask(
    async_client: AsyncClient,
    created_task: dict,
    logged_in_token: str,
    confirmed_user: dict,
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
        "user_id": confirmed_user["id"],
    }.items() <= response.json().items()


@pytest.mark.anyio
async def test_get_subtasks_on_task(
    async_client: AsyncClient, created_task: dict, created_subtask: dict, logged_in_token: str
):
    response = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}/subtask",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    assert response.status_code == 200
    assert response.json() == [created_subtask]


@pytest.mark.anyio
async def test_get_subtasks_on_task_empty(
    async_client: AsyncClient, created_task: dict, logged_in_token: str
):
    response = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}/subtask",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_get_task_with_subtasks(
    async_client: AsyncClient, created_task: dict, created_subtask: dict, logged_in_token: str
):
    response = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}/subtasks",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "task": created_task,
        "subtasks": [created_subtask],
    }


@pytest.mark.anyio
async def test_get_missing_task_with_subtasks(
    async_client: AsyncClient, created_subtask: dict, created_task: dict, logged_in_token: str
):
    response = await async_client.get(
        "/api/v1/tasks/999/subtasks", headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_create_tag(
    async_client: AsyncClient,
    created_task: dict,
    logged_in_token: str,
    confirmed_user: dict,
):
    body = {"name": "Important"}

    response = await async_client.post(
        f"/api/v1/tasks/{created_task['id']}/tags",
        json=body,
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    assert response.status_code == 201
    assert {
        "id": 1,
        "name": body["name"],
        "user_id": confirmed_user["id"],
    }.items() <= response.json().items()


@pytest.mark.anyio
async def test_get_tags_on_task(
    async_client: AsyncClient,
    created_task: dict,
    created_tag: dict,
    logged_in_token: str,
):
    response = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}/tags",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    assert response.status_code == 200
    assert response.json() == [created_tag]


@pytest.mark.anyio
async def test_get_tags_on_missing_task(async_client: AsyncClient, logged_in_token: str):
    response = await async_client.get(
        "/api/v1/tasks/999/tags",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_reuse_tag_across_tasks(db, async_client: AsyncClient, logged_in_token: str):
    first_task = await create_task({"title": "Task One"}, async_client, logged_in_token)
    second_task = await create_task({"title": "Task Two"}, async_client, logged_in_token)

    first_tag = await create_tag("Reusable", first_task["id"], async_client, logged_in_token)
    second_tag = await create_tag("Reusable", second_task["id"], async_client, logged_in_token)

    assert first_tag["id"] == second_tag["id"]

    auth_headers = {"Authorization": f"Bearer {logged_in_token}"}
    first_response = await async_client.get(
        f"/api/v1/tasks/{first_task['id']}/tags", headers=auth_headers
    )
    second_response = await async_client.get(
        f"/api/v1/tasks/{second_task['id']}/tags", headers=auth_headers
    )

    assert first_response.json() == [first_tag]
    assert second_response.json() == [first_tag]
