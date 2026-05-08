import pytest
from httpx import AsyncClient

from seed import seed_data


@pytest.mark.anyio
async def test_seed_data(async_client: AsyncClient, db):
    """
    Test that the seeding script successfully populates a confirmed user,
    with retrievable tasks, subtasks, and tags.
    """
    # 1. Run seed script
    await seed_data()

    # 2. Login as the seeded user
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": "seeduser@example.com", "password": "seedpassword123"},
    )
    assert response.status_code == 200, "Failed to login as seeded user"
    token = response.json()["access_token"]

    # 3. Retrieve tasks
    headers = {"Authorization": f"Bearer {token}"}
    tasks_response = await async_client.get("/api/v1/tasks/", headers=headers)
    assert tasks_response.status_code == 200

    tasks = tasks_response.json()
    assert len(tasks) == 2, "Seeded user should have exactly 2 tasks"

    task_titles = [task["title"] for task in tasks]
    assert "Complete Project Presentation" in task_titles
    assert "Weekly Groceries" in task_titles
