"""Tests for the /api/v1/users endpoints."""

from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession


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


@pytest.mark.anyio
async def test_register_user(db: AsyncSession, async_client: AsyncClient) -> None:
    """Verify a user can register."""
    response = await register_user(async_client, "newuser", "example@email.net", "newpassword")
    assert response.status_code == 201
    assert "User registered successfully." in response.json()["detail"]


@pytest.mark.anyio
async def test_confirm_user(db: AsyncSession, async_client: AsyncClient, mocker: Any) -> None:
    """Verify a user can confirm their email via the confirmation link."""
    mock_delay = mocker.patch("app.tasks.send_confirmation_email.delay")

    await register_user(async_client, "testuser", "test@example.net", "password123")
    assert mock_delay.called
    confirmation_url = str(mock_delay.call_args[1]["confirmation_url"])
    response = await async_client.get(confirmation_url)

    assert response.status_code == 200
    assert "Email Confirmed" in response.text


@pytest.mark.anyio
async def test_confirm_user_invalid_token(async_client: AsyncClient) -> None:
    """Verify confirming with an invalid token returns 401."""
    response = await async_client.get("/api/v1/users/confirm/invalidtoken")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_confirm_user_expired_token(async_client: AsyncClient, mocker: Any) -> None:
    """Verify confirming with an expired token returns 401."""
    mocker.patch("app.security.confirm_token_expire_time", return_value=-1)

    mock_delay = mocker.patch("app.tasks.send_confirmation_email.delay")
    await register_user(async_client, "testuser2", "test@exaple.net", "password123")
    assert mock_delay.called, (
        "Expected send_confirmation_email.delay to be called during registration"
    )
    confirmation_url = str(mock_delay.call_args[1]["confirmation_url"])
    response = await async_client.get(confirmation_url)

    assert response.status_code == 401
    assert "Token has expired" in response.json()["detail"]


@pytest.mark.anyio
async def test_register_user_duplicate_email(
    async_client: AsyncClient, registered_user: dict[str, Any]
) -> None:
    """Verify registering with a duplicate email returns 400."""
    response = await register_user(
        async_client, registered_user["username"], registered_user["email"], "anotherpassword"
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.anyio
async def test_login_user_not_exists(db: AsyncSession, async_client: AsyncClient) -> None:
    """Verify login with a non-existent user returns 401."""
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": "test@example.net", "password": "any"},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_login_user_not_confirmed(
    async_client: AsyncClient, registered_user: dict[str, Any]
) -> None:
    """Verify login for an unconfirmed user returns 401."""
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": registered_user["email"], "password": registered_user["password"]},
    )
    assert response.status_code == 401
    assert "Email not confirmed" in response.json()["detail"]


@pytest.mark.anyio
async def test_login_user(async_client: AsyncClient, confirmed_user: dict[str, Any]) -> None:
    """Verify a confirmed user can log in."""
    response = await async_client.post(
        "/api/v1/users/token",
        data={
            "username": confirmed_user["email"],
            "password": confirmed_user["password"],
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.anyio
async def test_logout_user(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify an authenticated user can log out."""
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.post("/api/v1/users/logout", headers=headers)
    assert response.status_code == 200
    assert "Successfully logged out" in response.json()["detail"]


@pytest.mark.anyio
async def test_logout_user_unauthenticated(async_client: AsyncClient) -> None:
    """Verify logout without auth does not error."""
    response = await async_client.post("/api/v1/users/logout")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_get_my_profile(
    async_client: AsyncClient, logged_in_token: str, confirmed_user: dict[str, Any]
) -> None:
    """Verify an authenticated user can fetch their profile."""
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == confirmed_user["username"]
    assert data["email"] == confirmed_user["email"]


@pytest.mark.anyio
async def test_update_username(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify a user can update their username."""
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


@pytest.mark.anyio
async def test_update_username_taken(
    async_client: AsyncClient, logged_in_token: str, db: AsyncSession
) -> None:
    """Verify updating to a taken username returns 400."""
    # Register another user
    await register_user(async_client, "otheruser", "other@example.com", "password")

    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.patch(
        "/api/v1/users/me/username", headers=headers, json={"username": "otheruser"}
    )
    assert response.status_code == 400
    assert "already taken" in response.json()["detail"]


@pytest.mark.anyio
async def test_update_password(
    async_client: AsyncClient, confirmed_user: dict[str, Any], logged_in_token: str
) -> None:
    """Verify a user can update their password."""
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


@pytest.mark.anyio
async def test_update_password_incorrect_current(
    async_client: AsyncClient, logged_in_token: str
) -> None:
    """Verify updating with an incorrect current password returns 400."""
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.patch(
        "/api/v1/users/me/password",
        headers=headers,
        json={"current_password": "wrongpassword", "new_password": "newpassword123"},
    )
    assert response.status_code == 400
    assert "Incorrect current password" in response.json()["detail"]


@pytest.mark.anyio
async def test_update_username_too_short(async_client: AsyncClient, logged_in_token: str) -> None:
    """Verify updating to a too-short username returns 400."""
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.patch(
        "/api/v1/users/me/username", headers=headers, json={"username": "ab"}
    )
    assert response.status_code == 400
    assert "at least 3 characters" in response.json()["detail"]


@pytest.mark.anyio
async def test_update_password_too_short(
    async_client: AsyncClient, confirmed_user: dict[str, Any], logged_in_token: str
) -> None:
    """Verify updating to a too-short password returns 400."""
    headers = {"Authorization": f"Bearer {logged_in_token}"}
    response = await async_client.patch(
        "/api/v1/users/me/password",
        headers=headers,
        json={"current_password": confirmed_user["password"], "new_password": "short"},
    )
    assert response.status_code == 400
    assert "at least 8 characters" in response.json()["detail"]
