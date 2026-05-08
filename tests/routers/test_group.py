import pytest
from httpx import AsyncClient
from sqlalchemy import update
from app.models.user import User

async def create_group(name: str, client: AsyncClient, token: str) -> dict:
    response = await client.post(
        "/api/v1/groups/",
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
    from sqlalchemy import select
    stmt = select(User).where(User.email == user_data["email"])
    result = await db.execute(stmt)
    user_data["id"] = result.scalar_one().id
    
    return user_data

@pytest.mark.anyio
async def test_create_group(async_client: AsyncClient, logged_in_token: str):
    response = await async_client.post(
        "/api/v1/groups/",
        json={"name": "Test Group", "color": "red"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Group"
    assert data["color"] == "red"
    assert "id" in data

@pytest.mark.anyio
async def test_list_groups(async_client: AsyncClient, logged_in_token: str):
    await create_group("Group 1", async_client, logged_in_token)
    await create_group("Group 2", async_client, logged_in_token)
    
    response = await async_client.get(
        "/api/v1/groups/",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

@pytest.mark.anyio
async def test_get_group(async_client: AsyncClient, logged_in_token: str):
    group = await create_group("My Group", async_client, logged_in_token)
    
    response = await async_client.get(
        f"/api/v1/groups/{group['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "My Group"

@pytest.mark.anyio
async def test_update_group(async_client: AsyncClient, logged_in_token: str):
    group = await create_group("Old Name", async_client, logged_in_token)
    
    response = await async_client.put(
        f"/api/v1/groups/{group['id']}",
        json={"name": "New Name"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"

@pytest.mark.anyio
async def test_delete_group(async_client: AsyncClient, logged_in_token: str):
    group = await create_group("To Delete", async_client, logged_in_token)
    
    response = await async_client.delete(
        f"/api/v1/groups/{group['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    
    # Verify gone
    response = await async_client.get(
        f"/api/v1/groups/{group['id']}",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 404

@pytest.mark.anyio
async def test_group_idor_protection(
    async_client: AsyncClient, logged_in_token: str, second_user: dict
):
    # User 1 creates a group
    group = await create_group("User 1 Group", async_client, logged_in_token)
    
    # User 2 tries to access it
    response = await async_client.get(
        f"/api/v1/groups/{group['id']}",
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 404
    
    # User 2 tries to update it
    response = await async_client.put(
        f"/api/v1/groups/{group['id']}",
        json={"name": "Hacked"},
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 404
    
    # User 2 tries to delete it
    response = await async_client.delete(
        f"/api/v1/groups/{group['id']}",
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 404

@pytest.mark.anyio
async def test_task_group_idor_protection(
    async_client: AsyncClient, logged_in_token: str, second_user: dict
):
    # User 1 creates a group
    group = await create_group("User 1 Group", async_client, logged_in_token)
    
    # User 2 tries to create a task in User 1's group
    response = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Hacker Task", "group_id": group["id"]},
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid group_id"
    
    # User 2 creates their own task
    response = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Legit Task"},
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 201
    task = response.json()
    
    # User 2 tries to update their task to belong to User 1's group
    response = await async_client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"group_id": group["id"]},
        headers={"Authorization": f"Bearer {second_user['token']}"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid group_id"

@pytest.mark.anyio
async def test_list_group_tasks(async_client: AsyncClient, logged_in_token: str):
    group = await create_group("Work", async_client, logged_in_token)
    
    # Create tasks in group
    await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Task 1", "group_id": group["id"]},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Task 2", "group_id": group["id"]},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    # Create task NOT in group
    await async_client.post(
        "/api/v1/tasks/",
        json={"title": "Task 3"},
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    
    response = await async_client.get(
        f"/api/v1/groups/{group['id']}/tasks",
        headers={"Authorization": f"Bearer {logged_in_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    for task in data:
        assert task["group_id"] == group["id"]
