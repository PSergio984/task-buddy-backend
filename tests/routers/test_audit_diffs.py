from httpx import AsyncClient

from app.schemas.enums import AuditAction


async def test_audit_task_update_diff(async_client: AsyncClient, logged_in_token: str):
    # 1. Create a task
    task_body = {"title": "Initial Title", "description": "Initial Description"}
    response = await async_client.post(
        "/api/v1/tasks/",
        json=task_body,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 201
    task_id = response.json()["id"]

    # 2. Update the task
    update_body = {"title": "Updated Title"}
    update_response = await async_client.put(
        f"/api/v1/tasks/{task_id}",
        json=update_body,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert update_response.status_code == 200

    # 3. Check audit logs
    audit_response = await async_client.get(
        "/api/v1/audit/logs",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert audit_response.status_code == 200
    logs = audit_response.json()

    # Verify an UPDATE task log exists with diff
    update_log = next((log for log in logs if log["target_type"] == "TASK" and log["action"] == AuditAction.UPDATE and log["target_id"] == task_id), None)
    assert update_log is not None
    assert "title: 'Initial Title' -> 'Updated Title'" in update_log["details"]

async def test_audit_project_update_diff(async_client: AsyncClient, logged_in_token: str):
    # 1. Create a project
    project_body = {"name": "Old Project", "color": "blue"}
    response = await async_client.post(
        "/api/v1/projects/",
        json=project_body,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 201
    project_id = response.json()["id"]

    # 2. Update the project
    update_body = {"name": "New Project", "color": "green"}
    update_response = await async_client.put(
        f"/api/v1/projects/{project_id}",
        json=update_body,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert update_response.status_code == 200

    # 3. Check audit logs
    audit_response = await async_client.get(
        "/api/v1/audit/logs",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert audit_response.status_code == 200
    logs = audit_response.json()

    # Verify an UPDATE project log exists with diff
    update_log = next((log for log in logs if log["target_type"] == "PROJECT" and log["action"] == AuditAction.UPDATE and log["target_id"] == project_id), None)
    assert update_log is not None
    assert "name: 'Old Project' -> 'New Project'" in update_log["details"]
    assert "color: 'blue' -> 'green'" in update_log["details"]

async def test_audit_task_deletion(async_client: AsyncClient, logged_in_token: str):
    # 1. Create a task
    task_body = {"title": "Delete Me"}
    response = await async_client.post(
        "/api/v1/tasks/",
        json=task_body,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 201
    task_id = response.json()["id"]

    # 2. Delete the task
    delete_response = await async_client.delete(
        f"/api/v1/tasks/{task_id}",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert delete_response.status_code == 200

    # 3. Check audit logs
    audit_response = await async_client.get(
        "/api/v1/audit/logs",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert audit_response.status_code == 200
    logs = audit_response.json()

    # Verify a DELETE task log exists
    delete_log = next((log for log in logs if log["target_type"] == "TASK" and log["action"] == AuditAction.DELETE and log["target_id"] == task_id), None)
    assert delete_log is not None
    assert "Delete task: Delete Me" in delete_log["details"]

