"""Tests for the /api/v1/tasks endpoints."""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import security


async def create_task(
    body: dict[str, Any], client: AsyncClient, logged_in_token: str
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    return cast(dict[str, Any], response.json())

async def create_subtask(
    body: str, task_id: int, client: AsyncClient, logged_in_token: str
) -> dict[str, Any]:

    response = await client.post(
        "/api/v1/tasks/subtask",
        json={"title": body, "task_id": task_id},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    return cast(dict[str, Any], response.json())

async def create_tag(
    body: str, task_id: int, client: AsyncClient, logged_in_token: str
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/tasks/{task_id}/tags",
        json={"name": body},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    return cast(dict[str, Any], response.json())

@pytest.fixture()
async def created_task(
    db: AsyncSession, async_client: AsyncClient, logged_in_token: str
) -> dict[str, Any]:
    return await create_task({"title": "Test Task"}, async_client, logged_in_token)


@pytest.fixture()
async def created_subtask(
    created_task: dict[str, Any], async_client: AsyncClient, logged_in_token: str
) -> dict[str, Any]:
    return await create_subtask("Test SubTask", created_task["id"], async_client, logged_in_token)


@pytest.fixture()
async def created_tag(
    created_task: dict[str, Any], async_client: AsyncClient, logged_in_token: str
) -> dict[str, Any]:
    return await create_tag("Important", created_task["id"], async_client, logged_in_token)


@pytest.mark.anyio
async def test_create_task(
    db: AsyncSession, async_client: AsyncClient, logged_in_token: str, confirmed_user: dict[str, Any]
) -> None:
    """Verify a user can create a task."""
    body = {"title": "Test Task"}

    response = await async_client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == body["title"]
    assert data["user_id"] == confirmed_user["id"]
    assert "id" in data


@pytest.mark.anyio
async def test_create_empty_task(
    db: AsyncSession, async_client: AsyncClient, logged_in_token: str
) -> None:
    """Verify creating a task with an empty body returns 422."""

    response = await async_client.post(
        "/api/v1/tasks/", json={}, headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_task_expired_token(
    db: AsyncSession, async_client: AsyncClient, confirmed_user: dict[str, Any], monkeypatch: Any
) -> None:
    """Verify creating a task with an expired token returns 401."""
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
async def test_get_all_tasks(
    async_client: AsyncClient, created_task: dict[str, Any], logged_in_token: str
) -> None:
    """Verify a user can list their tasks."""
    response = await async_client.get(
        "/api/v1/tasks/", headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 200
    assert response.json() == [created_task]


@pytest.mark.anyio
async def test_create_subtask(
    async_client: AsyncClient,
    created_task: dict[str, Any],
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """Verify a user can create a subtask."""
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
    async_client: AsyncClient, created_task: dict[str, Any], created_subtask: dict[str, Any], logged_in_token: str
) -> None:
    """Verify subtasks are listed on a task."""
    response = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}/subtask",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    assert response.status_code == 200
    assert response.json() == [created_subtask]


@pytest.mark.anyio
async def test_get_subtasks_on_task_empty(
    async_client: AsyncClient, created_task: dict[str, Any], logged_in_token: str
) -> None:
    """Verify a task without subtasks returns an empty list."""
    response = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}/subtask",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_get_task_with_subtasks(
    async_client: AsyncClient, created_task: dict[str, Any], created_subtask: dict[str, Any], logged_in_token: str
) -> None:
    """Verify a task response includes its subtasks."""
    response = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}/subtasks",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    expected_task = created_task.copy()
    expected_task["subtasks"] = [created_subtask]

    assert response.json() == {
        "task": expected_task,
        "subtasks": [created_subtask],
    }


@pytest.mark.anyio
async def test_get_missing_task_with_subtasks(
    async_client: AsyncClient, created_subtask: dict[str, Any], created_task: dict[str, Any], logged_in_token: str
) -> None:
    """Verify fetching subtasks of a missing task returns 404."""
    response = await async_client.get(
        "/api/v1/tasks/999/subtasks", headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_create_tag(
    async_client: AsyncClient,
    created_task: dict[str, Any],
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """Verify a user can create a tag on a task."""
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
    created_task: dict[str, Any],
    created_tag: dict[str, Any],
    logged_in_token: str,
) -> None:
    """Verify tags are listed on a task."""
    response = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}/tags",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    assert response.status_code == 200
    assert response.json() == [created_tag]


@pytest.mark.anyio
async def test_get_tags_on_missing_task(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify fetching tags of a missing task returns 404."""
    response = await async_client.get(
        "/api/v1/tasks/999/tags",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_reuse_tag_across_tasks(
    db: AsyncSession, async_client: AsyncClient, logged_in_token: str
) -> None:
    """Verify a tag is reused rather than duplicated across tasks."""
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


@pytest.mark.anyio
async def test_update_task(
    async_client: AsyncClient, created_task: dict[str, Any], logged_in_token: str
) -> None:
    """Verify a user can update a task."""
    response = await async_client.put(
        f"/api/v1/tasks/{created_task['id']}",
        json={"title": "Updated Title", "completed": True},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200

    # Verify update
    get_resp = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert get_resp.json()["title"] == "Updated Title"
    assert get_resp.json()["completed"] is True


@pytest.mark.anyio
async def test_delete_task(
    async_client: AsyncClient, created_task: dict[str, Any], logged_in_token: str
) -> None:
    """Verify a user can delete a task."""
    response = await async_client.delete(
        f"/api/v1/tasks/{created_task['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200

    # Verify deletion
    get_resp = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert get_resp.status_code == 404


@pytest.mark.anyio
async def test_update_subtask(
    async_client: AsyncClient, created_subtask: dict[str, Any], logged_in_token: str
) -> None:
    """Verify a user can update a subtask."""
    response = await async_client.put(
        f"/api/v1/tasks/subtask/{created_subtask['id']}",
        json={"title": "Updated Subtask", "completed": True},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200

    # Verify update
    get_resp = await async_client.get(
        f"/api/v1/tasks/subtask/{created_subtask['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert get_resp.json()["title"] == "Updated Subtask"
    assert get_resp.json()["completed"] is True


@pytest.mark.anyio
async def test_delete_subtask(
    async_client: AsyncClient, created_subtask: dict[str, Any], logged_in_token: str
) -> None:
    """Verify a user can delete a subtask."""
    response = await async_client.delete(
        f"/api/v1/tasks/subtask/{created_subtask['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200

    # Verify deletion
    get_resp = await async_client.get(
        f"/api/v1/tasks/subtask/{created_subtask['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert get_resp.status_code == 404


@pytest.mark.anyio
async def test_get_tasks_filtered_by_project(
    async_client: AsyncClient, logged_in_token: str
) -> None:
    """Verify tasks can be filtered by project_id."""
    # Create a project
    project_resp = await async_client.post(
        "/api/v1/projects/",
        json={"name": "Work", "color": "blue"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert project_resp.status_code == 201
    project_id = project_resp.json()["id"]

    # Create tasks: one in project, one out
    task_in = await create_task({"title": "In Project", "project_id": project_id}, async_client, logged_in_token)
    task_out = await create_task({"title": "Out of Project"}, async_client, logged_in_token)

    # Fetch with project_id filter
    response = await async_client.get(
        f"/api/v1/tasks/?project_id={project_id}",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == task_in["id"]
    assert data[0]["project_id"] == project_id

    # Assert that the task out of project is NOT in the results
    assert task_out["id"] not in [t["id"] for t in data]


@pytest.mark.anyio
async def test_detach_tag(
    async_client: AsyncClient, created_task: dict[str, Any], created_tag: dict[str, Any], logged_in_token: str
) -> None:
    """Verify a user can detach a tag from a task."""
    response = await async_client.delete(
        f"/api/v1/tasks/{created_task['id']}/tags/{created_tag['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200

    # Verify detached
    get_resp = await async_client.get(
        f"/api/v1/tasks/{created_task['id']}/tags",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert created_tag not in get_resp.json()


@pytest.mark.anyio
async def test_delete_tag(
    async_client: AsyncClient, created_tag: dict[str, Any], logged_in_token: str
) -> None:
    """Verify a user can delete a tag."""
    response = await async_client.delete(
        f"/api/v1/tasks/tags/{created_tag['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_create_task_limit_tags(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify task creation is limited to 10 tags."""
    # 11 tags - should fail
    body = {
        "title": "Task with too many tags",
        "tags": [f"tag_{i}" for i in range(11)]
    }
    response = await async_client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot exceed 10 tags per task"

    # 10 tags - should pass
    body_ok = {
        "title": "Task with exactly 10 tags",
        "tags": [f"tag_{i}" for i in range(10)]
    }
    response_ok = await async_client.post(
        "/api/v1/tasks/", json=body_ok, headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response_ok.status_code == 201


@pytest.mark.anyio
async def test_create_task_limit_subtasks(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify task creation is limited to 50 subtasks."""
    # 51 subtasks - should fail
    body = {
        "title": "Task with too many subtasks",
        "subtasks": [{"title": f"subtask_{i}"} for i in range(51)]
    }
    response = await async_client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot exceed 50 subtasks per task"

    # 50 subtasks - should pass
    body_ok = {
        "title": "Task with exactly 50 subtasks",
        "subtasks": [{"title": f"subtask_{i}"} for i in range(50)]
    }
    response_ok = await async_client.post(
        "/api/v1/tasks/", json=body_ok, headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response_ok.status_code == 201


@pytest.mark.anyio
async def test_update_task_limit_tags(
    async_client: AsyncClient, created_task: dict[str, Any], logged_in_token: str
) -> None:
    """Verify task updates are limited to 10 tags."""
    # 11 tags - should fail
    response = await async_client.put(
        f"/api/v1/tasks/{created_task['id']}",
        json={"tags": [f"tag_{i}" for i in range(11)]},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot exceed 10 tags per task"

    # 10 tags - should pass
    response_ok = await async_client.put(
        f"/api/v1/tasks/{created_task['id']}",
        json={"tags": [f"tag_{i}" for i in range(10)]},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response_ok.status_code == 200


@pytest.mark.anyio
async def test_create_subtask_limit(
    async_client: AsyncClient, created_task: dict[str, Any], logged_in_token: str
) -> None:
    """Verify subtask creation is limited to 50 per task."""
    # Add 50 subtasks
    for i in range(50):
        resp = await async_client.post(
            "/api/v1/tasks/subtask",
            json={"title": f"Sub_{i}", "task_id": created_task["id"]},
            headers={"Authorization": f"Bearer {logged_in_token}"},
        )
        assert resp.status_code == 201

    # Try to add 51st subtask - should fail
    resp_fail = await async_client.post(
        "/api/v1/tasks/subtask",
        json={"title": "Sub_51", "task_id": created_task["id"]},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert resp_fail.status_code == 400
    assert resp_fail.json()["detail"] == "Cannot exceed 50 subtasks per task"


@pytest.mark.anyio
async def test_create_tag_limit(
    async_client: AsyncClient, created_task: dict[str, Any], logged_in_token: str
) -> None:
    """Verify tag creation is limited to 10 per task."""
    # Add 10 tags
    for i in range(10):
        resp = await async_client.post(
            f"/api/v1/tasks/{created_task['id']}/tags",
            json={"name": f"tag_{i}"},
            headers={"Authorization": f"Bearer {logged_in_token}"},
        )
        assert resp.status_code == 201

    # Try to add 11th tag - should fail
    resp_fail = await async_client.post(
        f"/api/v1/tasks/{created_task['id']}/tags",
        json={"name": "tag_11"},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert resp_fail.status_code == 400
    assert resp_fail.json()["detail"] == "Cannot exceed 10 tags per task"

    # Re-adding a tag that is already on the task is allowed (idempotent / already attached check)
    resp_dup = await async_client.post(
        f"/api/v1/tasks/{created_task['id']}/tags",
        json={"name": "tag_0"},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert resp_dup.status_code == 201


@pytest.mark.anyio
async def test_attach_tag_limit(
    async_client: AsyncClient, created_task: dict[str, Any], logged_in_token: str
) -> None:
    """Verify attaching tags is limited to 10 per task."""
    # Create 11 tags in the system
    tag_ids = []
    for i in range(11):
        resp = await async_client.post(
            "/api/v1/tasks/tags/",
            json={"name": f"unique_tag_{i}"},
            headers={"Authorization": f"Bearer {logged_in_token}"},
        )
        assert resp.status_code == 201
        tag_ids.append(resp.json()["id"])

    # Attach 10 tags to created_task
    for tag_id in tag_ids[:10]:
        resp = await async_client.post(
            f"/api/v1/tasks/{created_task['id']}/tags/{tag_id}",
            headers={"Authorization": f"Bearer {logged_in_token}"},
        )
        assert resp.status_code == 200

    # Try to attach 11th tag - should fail
    resp_fail = await async_client.post(
        f"/api/v1/tasks/{created_task['id']}/tags/{tag_ids[10]}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert resp_fail.status_code == 400
    assert resp_fail.json()["detail"] == "Cannot exceed 10 tags per task"
