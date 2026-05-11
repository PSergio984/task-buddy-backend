import asyncio

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_concurrent_task_creation(authenticated_async_client: AsyncClient):
    """Test creating multiple tasks concurrently."""
    num_tasks = 20
    tasks_data = [
        {"title": f"Concurrent Task {i}", "description": f"Description {i}"}
        for i in range(num_tasks)
    ]

    # Create tasks concurrently
    responses = await asyncio.gather(
        *[
            authenticated_async_client.post("/api/v1/tasks/", json=data)
            for data in tasks_data
        ]
    )

    # Verify all tasks were created successfully
    for response in responses:
        assert response.status_code == 201, f"Task creation failed: {response.text}"

    # Verify we can fetch them all
    list_response = await authenticated_async_client.get("/api/v1/tasks/")
    assert list_response.status_code == 200
    assert len(list_response.json()) >= num_tasks


@pytest.mark.asyncio
async def test_concurrent_task_updates_same_task(authenticated_async_client: AsyncClient):
    """Test updating the SAME task concurrently to check for deadlocks/race conditions."""
    # 1. Create a task
    create_resp = await authenticated_async_client.post(
        "/api/v1/tasks/", json={"title": "Original Title", "description": "Original Desc"}
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]

    # 2. Fire simultaneous updates
    num_updates = 20
    updates = [
        authenticated_async_client.put(
            f"/api/v1/tasks/{task_id}", json={"title": f"Updated Title {i}"}
        )
        for i in range(num_updates)
    ]

    responses = await asyncio.gather(*updates)

    # 3. Verify all responses are successful
    # Some might get 'row locked' errors if we used strict locking,
    # but in SQLite/FastAPI with async, it should handle them or wait.
    for response in responses:
        assert response.status_code == 200, f"Task update failed: {response.text}"

    # 4. Final state should be one of the updates
    final_resp = await authenticated_async_client.get(f"/api/v1/tasks/{task_id}")
    assert final_resp.status_code == 200
    assert final_resp.json()["title"].startswith("Updated Title")


@pytest.mark.asyncio
async def test_concurrent_project_creation(authenticated_async_client: AsyncClient):
    """Test creating multiple projects concurrently."""
    num_projects = 10
    projects_data = [
        {"name": f"Project {i}", "description": f"Desc {i}"}
        for i in range(num_projects)
    ]

    responses = await asyncio.gather(
        *[
            authenticated_async_client.post("/api/v1/projects/", json=data)
            for data in projects_data
        ]
    )

    for response in responses:
        assert response.status_code == 201, f"Project creation failed: {response.text}"
