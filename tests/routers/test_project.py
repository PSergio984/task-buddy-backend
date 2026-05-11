import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.models.user import User


async def create_project(name: str, client: AsyncClient, token: str) -> dict:
    response = await client.post(
        "/api/v1/projects/",
        json={"name": name, "color": "blue"},
        headers={"Authorization": f"Bearer {token}"}
    )
    return response.json()

@pytest.fixture()
async def second_user(db, async_client: AsyncClient) -> dict:
    user_data = {
        "username": "seconduser",
        "email": "second@example.com",
        "password": "secondpassword",
    }
    response = await async_client.post("/api/v1/users/register", json=user_data)
    assert response.status_code == 201

    # Confirm user
    stmt = update(User).where(User.email == user_data["email"]).values(confirmed=True)
    await db.execute(stmt)
    await db.commit()

    # Get token
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": user_data["email"], "password": user_data["password"]},
    )
    assert response.status_code == 200
    user_data["token"] = response.json()["access_token"]

    # Get ID
    stmt = select(User).where(User.email == user_data["email"])
    result = await db.execute(stmt)
    user_data["id"] = result.scalar_one().id

    return user_data

async def test_create_project(async_client: AsyncClient, logged_in_token: str):
    response = await async_client.post(
        "/api/v1/projects/",
        json={"name": "Test Project", "color": "red"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Project"
    assert data["color"] == "red"
    assert "id" in data

async def test_list_projects(async_client: AsyncClient, logged_in_token: str):
    await create_project("Project 1", async_client, logged_in_token)
    await create_project("Project 2", async_client, logged_in_token)

    response = await async_client.get(
        "/api/v1/projects/",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

async def test_get_project(async_client: AsyncClient, logged_in_token: str):
    project = await create_project("My Project", async_client, logged_in_token)

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "My Project"

async def test_update_project(async_client: AsyncClient, logged_in_token: str):
    project = await create_project("Old Name", async_client, logged_in_token)

    response = await async_client.put(
        f"/api/v1/projects/{project['id']}",
        json={"name": "New Name"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"

async def test_delete_project(async_client: AsyncClient, logged_in_token: str):
    project = await create_project("To Delete", async_client, logged_in_token)

    response = await async_client.delete(
        f"/api/v1/projects/{project['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200

    # Verify gone
    response = await async_client.get(
        f"/api/v1/projects/{project['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 404

async def test_project_idor_protection(
    async_client: AsyncClient, logged_in_token: str, second_user: dict
):
    # User 1 creates a project
    project = await create_project("User 1 Project", async_client, logged_in_token)

    # User 2 tries to access it
    response = await async_client.get(
        f"/api/v1/projects/{project['id']}",
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 404

    # User 2 tries to update it
    response = await async_client.put(
        f"/api/v1/projects/{project['id']}",
        json={"name": "Hacked"},
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 404

    # User 2 tries to delete it
    response = await async_client.delete(
        f"/api/v1/projects/{project['id']}",
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 404

async def test_task_project_idor_protection(
    async_client: AsyncClient, logged_in_token: str, second_user: dict
):
    # User 1 creates a project
    project = await create_project("User 1 Project", async_client, logged_in_token)

    # User 2 tries to create a task in User 1's project
    response = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Hacker Task", "project_id": project["id"]},
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid project_id"

    # User 2 creates their own task
    response = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Legit Task"},
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 201
    task = response.json()

    # User 2 tries to update their task to belong to User 1's project
    response = await async_client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"project_id": project["id"]},
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid project_id"

async def test_list_project_tasks(async_client: AsyncClient, logged_in_token: str):
    project = await create_project("Work", async_client, logged_in_token)

    # Create tasks in project
    await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Task 1", "project_id": project["id"]},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Task 2", "project_id": project["id"]},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    # Create task NOT in project
    await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Task 3"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/tasks",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    for task in data:
        assert task["project_id"] == project["id"]

async def test_create_duplicate_project_error(async_client: AsyncClient, logged_in_token: str):
    # Create first project
    project_data = {"name": "Duplicate Project", "color": "blue"}
    response = await async_client.post(
        "/api/v1/projects/",
        json=project_data,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 201

    # Try to create duplicate project
    response = await async_client.post(
        "/api/v1/projects/",
        json=project_data,
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Project with this name already exists"
