from httpx import AsyncClient


async def test_get_audit_logs_empty(async_client: AsyncClient, logged_in_token: str):
    response = await async_client.get(
        "/api/v1/audit/logs",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    # Because getting the logged_in_token performs a login, there will be at least one audit log (login)
    logs = response.json()
    assert len(logs) > 0
    assert any(log["action"] == "login" for log in logs)


async def test_audit_log_after_task_creation(async_client: AsyncClient, logged_in_token: str):
    # 1. Create a task
    task_data = {"title": "Test Task", "description": "Testing audit logs"}
    create_response = await async_client.post(
        "/api/v1/tasks/",
        json=task_data,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # 2. Check audit logs
    logs_response = await async_client.get(
        "/api/v1/audit/logs",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert len(logs) >= 1

    # Find the CREATE TASK log (action might be 'create' or similar)
    task_log = next((log for log in logs if log["action"] == "create" and log["target_type"] == "TASK" and log["target_id"] == task_id), None)

    if task_log is None:
        # Fallback for debugging, if the action is different, we can see the available logs
        raise AssertionError(f"Could not find CREATE TASK log for task_id {task_id}. Available logs: {logs}")

    assert task_log["target_id"] == task_id
    assert "Test Task" in task_log.get("details", "")


async def test_audit_log_filtering(async_client: AsyncClient, logged_in_token: str):
    # Create multiple tasks
    for i in range(3):
        await async_client.post(
            "/api/v1/tasks/",
            json={"title": f"Task {i}"},
            headers={"Authorization": f"Bearer {logged_in_token}"}
        )

    # Fetch logs limited to 2
    response = await async_client.get(
        "/api/v1/audit/logs?limit=2",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    assert len(response.json()) == 2
    response = await async_client.get(
        "/api/v1/audit/logs?action=NON_EXISTENT",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    assert response.json() == []
