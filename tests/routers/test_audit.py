"""Tests for the /api/v1/audit logs endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_get_audit_logs_empty(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify audit logs are returned for a logged-in user."""
    response = await async_client.get(
        "/api/v1/audit/logs", headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    # Because getting the logged_in_token performs a login, there will be at least one audit log (login)
    logs = response.json()
    assert len(logs) > 0
    assert any(log["action"] == "login" for log in logs)


@pytest.mark.anyio
async def test_audit_log_after_task_creation(
    async_client: AsyncClient, logged_in_token: str
) -> None:
    """Verify a create log is recorded when a task is created."""
    # 1. Create a task
    task_data = {"title": "Test Task", "description": "Testing audit logs"}
    create_response = await async_client.post(
        "/api/v1/tasks/", json=task_data, headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # 2. Check audit logs
    logs_response = await async_client.get(
        "/api/v1/audit/logs", headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert len(logs) >= 1

    # Find the CREATE TASK log (action might be 'create' or similar)
    task_log = next(
        (
            log
            for log in logs
            if log["action"] == "create"
            and log["target_type"] == "TASK"
            and log["target_id"] == task_id
        ),
        None,
    )

    if task_log is None:
        # Fallback for debugging, if the action is different, we can see the available logs
        raise AssertionError(
            f"Could not find CREATE TASK log for task_id {task_id}. Available logs: {logs}"
        )

    assert task_log["target_id"] == task_id
    assert "Test Task" in task_log.get("details", "")


@pytest.mark.anyio
async def test_audit_log_filtering(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify audit logs support limit and action filters."""
    # Create multiple tasks
    for i in range(3):
        await async_client.post(
            "/api/v1/tasks/",
            json={"title": f"Task {i}"},
            headers={"Authorization": f"Bearer {logged_in_token}"},
        )

    # Fetch logs limited to 2
    response = await async_client.get(
        "/api/v1/audit/logs?limit=2", headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    assert len(response.json()) == 2
    response = await async_client.get(
        "/api/v1/audit/logs?action=NON_EXISTENT",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_audit_log_date_and_action_filtering(
    async_client: AsyncClient, logged_in_token: str
) -> None:
    """Verify audit logs support date-range and action filters."""
    from datetime import datetime, timedelta

    # 1. Create a task to generate a create log
    await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Audit Date Filter Task"},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )

    now = datetime.utcnow()
    start_date = (now - timedelta(minutes=5)).isoformat()
    end_date = (now + timedelta(minutes=5)).isoformat()
    future_date = (now + timedelta(days=1)).isoformat()
    past_date = (now - timedelta(days=1)).isoformat()

    # Query with date range containing now should return logs
    response = await async_client.get(
        f"/api/v1/audit/logs?start_date={start_date}&end_date={end_date}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) > 0

    # Query with date range in future should return empty list
    response = await async_client.get(
        f"/api/v1/audit/logs?start_date={future_date}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 0

    # Query with date range in past should return empty list
    response = await async_client.get(
        f"/api/v1/audit/logs?end_date={past_date}",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 0

    # Query with action filter
    response = await async_client.get(
        "/api/v1/audit/logs?action=create", headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) > 0
    assert all(log["action"] == "create" for log in logs)
