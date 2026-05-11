from fastapi import BackgroundTasks
from httpx import AsyncClient, Response


async def register_user(
    async_client: AsyncClient, username: str, email: str, password: str
) -> Response:
    return await async_client.post(
        "/api/v1/users/register",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )


async def test_register_user(db, async_client: AsyncClient):
    response = await register_user(async_client, "newuser", "example@email.net", "newpassword")
    assert response.status_code == 201
    assert "User registered successfully." in response.json()["detail"]


async def test_confirm_user(db, async_client: AsyncClient, mocker):
    spy = mocker.spy(BackgroundTasks, "add_task")

    await register_user(async_client, "testuser", "test@example.net", "1234")
    confirmation_url = str(spy.call_args[1]["confirmation_url"])
    response = await async_client.get(confirmation_url)

    assert response.status_code == 200
    assert "Email confirmed" in response.json()["detail"]


async def test_confirm_user_invalid_token(async_client: AsyncClient):
    response = await async_client.get("/api/v1/users/confirm/invalidtoken")
    assert response.status_code == 401


async def test_confirm_user_expired_token(async_client: AsyncClient, mocker):
    mocker.patch("app.security.confirm_token_expire_time", return_value=-1)

    spy = mocker.spy(BackgroundTasks, "add_task")
    await register_user(async_client, "testuser2", "test@exaple.net", "1234")
    assert spy.called, "Expected add_task to be called during registration"
    confirmation_url = str(spy.call_args[1]["confirmation_url"])
    response = await async_client.get(confirmation_url)

    assert response.status_code == 401
    assert "Token has expired" in response.json()["detail"]


async def test_register_user_duplicate_email(async_client: AsyncClient, registered_user: dict):
    response = await register_user(
        async_client, registered_user["username"], registered_user["email"], "anotherpassword"
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


async def test_login_user_not_exists(db, async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": "test@example.net", "password": "any"},
    )
    assert response.status_code == 401


async def test_login_user_not_confirmed(async_client: AsyncClient, registered_user: dict):
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": registered_user["email"], "password": registered_user["password"]},
    )
    assert response.status_code == 401
    assert "Invalid credentials" in response.json()["detail"]


async def test_login_user(async_client: AsyncClient, confirmed_user: dict):
    response = await async_client.post(
        "/api/v1/users/token",
        data={
            "username": confirmed_user["email"],
            "password": confirmed_user["password"],
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_logout_user(async_client: AsyncClient, logged_in_token: str):
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.post("/api/v1/users/logout", headers=headers)
    assert response.status_code == 200
    assert "Successfully logged out" in response.json()["detail"]


async def test_logout_user_unauthenticated(async_client: AsyncClient):
    response = await async_client.post("/api/v1/users/logout")
    assert response.status_code == 200


async def test_get_my_profile(async_client: AsyncClient, logged_in_token: str, confirmed_user: dict):
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == confirmed_user["username"]
    assert data["email"] == confirmed_user["email"]


async def test_update_username(async_client: AsyncClient, logged_in_token: str):
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    new_username = "updatedname"
    response = await async_client.patch(
        "/api/v1/users/me/username", headers=headers, json={"username": new_username}
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Username updated successfully"

    # Verify change
    profile_response = await async_client.get("/api/v1/users/me", headers=headers)
    assert profile_response.json()["username"] == new_username


async def test_update_username_taken(async_client: AsyncClient, logged_in_token: str, db):
    # Register another user
    await register_user(async_client, "otheruser", "other@example.com", "password")

    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.patch(
        "/api/v1/users/me/username", headers=headers, json={"username": "otheruser"}
    )
    assert response.status_code == 400
    assert "already taken" in response.json()["detail"]


async def test_update_password(async_client: AsyncClient, confirmed_user: dict, logged_in_token: str):
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    new_password = "newsecurepassword"
    response = await async_client.patch(
        "/api/v1/users/me/password",
        headers=headers,
        json={"current_password": confirmed_user["password"], "new_password": new_password},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Password updated successfully"

    # Verify login with new password
    login_response = await async_client.post(
        "/api/v1/users/token",
        data={"username": confirmed_user["email"], "password": new_password},
    )
    assert login_response.status_code == 200


async def test_update_password_incorrect_current(async_client: AsyncClient, logged_in_token: str):
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.patch(
        "/api/v1/users/me/password",
        headers=headers,
        json={"current_password": "wrongpassword", "new_password": "newpassword123"},
    )
    assert response.status_code == 400
    assert "Incorrect current password" in response.json()["detail"]


async def test_update_username_too_short(async_client: AsyncClient, logged_in_token: str):
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.patch(
        "/api/v1/users/me/username", headers=headers, json={"username": "ab"}
    )
    assert response.status_code == 400
    assert "at least 3 characters" in response.json()["detail"]


async def test_update_password_too_short(async_client: AsyncClient, confirmed_user: dict, logged_in_token: str):
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.patch(
        "/api/v1/users/me/password",
        headers=headers,
        json={"current_password": confirmed_user["password"], "new_password": "short"},
    )
    assert response.status_code == 400
    assert "at least 8 characters" in response.json()["detail"]
