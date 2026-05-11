from httpx import AsyncClient

from app.schemas.enums import AuditAction


async def test_audit_task_creation(async_client: AsyncClient, logged_in_token: str):
    # 1. Create a task
    task_body = {"title": "Audit Test Task"}
    response = await async_client.post(
        "/api/v1/tasks/",
        json=task_body,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 201
    task_id = response.json()["id"]

    # 2. Check audit logs
    audit_response = await async_client.get(
        "/api/v1/audit/logs",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert audit_response.status_code == 200
    logs = audit_response.json()

    # Verify a CREATE task log exists
    relevant_log = next((log for log in logs if log["target_type"] == "TASK" and log["action"] == AuditAction.CREATE), None)
    assert relevant_log is not None
    assert relevant_log["target_id"] == task_id

async def test_audit_project_creation(async_client: AsyncClient, logged_in_token: str):
    # 1. Create a project
    project_body = {"name": "Audit Test Project", "color": "red"}
    response = await async_client.post(
        "/api/v1/projects/",
        json=project_body,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 201
    project_id = response.json()["id"]

    # 2. Check audit logs
    audit_response = await async_client.get(
        "/api/v1/audit/logs",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert audit_response.status_code == 200
    logs = audit_response.json()

    # Verify a CREATE project log exists
    relevant_log = next((log for log in logs if log["target_type"] == "PROJECT" and log["action"] == AuditAction.CREATE), None)
    assert relevant_log is not None
    assert relevant_log["target_id"] == project_id

async def test_audit_tag_creation(async_client: AsyncClient, logged_in_token: str):
    # 1. Create a task first (to attach tag to)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Tag Audit Task"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    task_id = task_resp.json()["id"]

    # 2. Create a tag via task endpoint
    tag_body = {"name": "AuditTag"}
    response = await async_client.post(
        f"/api/v1/tasks/{task_id}/tags",
        json=tag_body,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 201
    tag_id = response.json()["id"]

    # 3. Check audit logs
    audit_response = await async_client.get(
        "/api/v1/audit/logs",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert audit_response.status_code == 200
    logs = audit_response.json()

    # Verify a CREATE tag log exists
    relevant_log = next((log for log in logs if log["target_type"] == "TAG" and log["action"] == AuditAction.CREATE), None)
    assert relevant_log is not None
    assert relevant_log["target_id"] == tag_id
