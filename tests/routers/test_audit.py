import pytest
from httpx import AsyncClient

@pytest.mark.anyio
async def test_get_audit_logs_empty(async_client: AsyncClient, logged_in_token: str):
    response = await async_client.get(
        "/api/v1/audit/logs",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.anyio
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
    
    # Find the CREATE TASK log
    task_log = next((log for log in logs if log["action"] == "CREATE" and log["target_type"] == "TASK"), None)
    assert task_log is not None
    assert task_log["target_id"] == task_id
    assert "Test Task" in task_log["details"]

@pytest.mark.anyio
async def test_audit_log_filtering(async_client: AsyncClient, logged_in_token: str):
    # Create another task to ensure multiple logs
    await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Another Task"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    
    # Filter by action
    response = await async_client.get(
        "/api/v1/audit/logs?action=CREATE",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    logs = response.json()
    assert all(log["action"] == "CREATE" for log in logs)
    
    # Filter by non-existent action
    response = await async_client.get(
        "/api/v1/audit/logs?action=NON_EXISTENT",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    assert response.json() == []
