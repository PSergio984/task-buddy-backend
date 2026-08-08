"""Tests for the /api/v1/stats endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_get_stats_overview_empty(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify stats overview returns zeros for a user with no data."""
    response = await async_client.get(
        "/api/v1/stats/overview",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["task_stats"]["total_tasks"] == 0
    assert data["task_stats"]["completed_tasks"] == 0
    assert data["tag_distribution"] == []

@pytest.mark.anyio
async def test_stats_with_data(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify stats overview reflects created tasks."""
    # 1. Create tasks
    task1_response = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Task 1", "completed": True},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert task1_response.status_code == 201, f"Task 1 creation failed: {task1_response.text}"
    task2_response = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Task 2", "completed": False},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert task2_response.status_code == 201, f"Task 2 creation failed: {task2_response.text}"

    # 2. Get stats
    response = await async_client.get(
        "/api/v1/stats/overview",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["task_stats"]["total_tasks"] == 2
    assert data["task_stats"]["completed_tasks"] == 1
    assert data["task_stats"]["pending_tasks"] == 1
    assert data["task_stats"]["completion_percentage"] == pytest.approx(50.0)

@pytest.mark.anyio
async def test_tag_distribution(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify tag distribution in stats reflects created tags."""
    # 1. Create task and tag
    create_response = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Tagged Task"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert create_response.status_code == 201, f"Task creation failed: {create_response.text}"
    task_id = create_response.json()["id"]

    tag_response = await async_client.post(
        f"/api/v1/tasks/{task_id}/tags",
        json={"name": "Work"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert tag_response.status_code == 201, f"Tag creation failed: {tag_response.text}"

    # 2. Get stats
    response = await async_client.get(
        "/api/v1/stats/overview",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    data = response.json()

    assert len(data["tag_distribution"]) == 1
    assert data["tag_distribution"][0]["tag_name"] == "Work"
    assert data["tag_distribution"][0]["task_count"] == 1
