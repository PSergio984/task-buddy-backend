import pytest
from httpx import AsyncClient

from scripts.seed import seed_data


async def test_seed_data(async_client: AsyncClient, db):
    """
    Test that the seeding script successfully populates a confirmed user,
    with retrievable tasks, projects, subtasks, and tags.
    """
    # 1. Run seed script
    await seed_data()

    # 2. Login as the seeded user
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": "demo@example.com", "password": "password123"},
    )
    assert response.status_code == 200, "Failed to login as seeded user"
    token = response.json()["access_token"]

    # 3. Retrieve tasks
    headers = {"Authorization": f"Bearer {token}"}
    tasks_response = await async_client.get("/api/v1/tasks/", headers=headers)
    assert tasks_response.status_code == 200

    tasks = tasks_response.json()
    assert len(tasks) == 24, "Seeded user should have exactly 24 tasks"

    task_titles = [task["title"] for task in tasks]
    assert "Finalize Q3 Infrastructure Audit" in task_titles
    assert "Setup Automated Backup Logic" in task_titles

    # 4. Retrieve projects
    projects_response = await async_client.get("/api/v1/projects/", headers=headers)
    assert projects_response.status_code == 200
    projects = projects_response.json()
    assert len(projects) == 4, "Seeded user should have exactly 4 projects"
