from fastapi import BackgroundTasks
from httpx import AsyncClient

from app.security import create_reset_token


async def test_forgot_password_success(async_client: AsyncClient, confirmed_user: dict, mocker):
    spy = mocker.spy(BackgroundTasks, "add_task")

    response = await async_client.post(
        "/api/v1/users/forgot-password",
        json={"email": confirmed_user["email"]}
    )

    assert response.status_code == 200
    assert "reset link has been sent" in response.json()["detail"]
    assert spy.called

    # Check reset URL in background task call
    reset_url = spy.call_args[1]["reset_url"]
    assert "/api/v1/users/reset-password/" in reset_url

async def test_forgot_password_user_not_found(async_client: AsyncClient, mocker):
    spy = mocker.spy(BackgroundTasks, "add_task")

    response = await async_client.post(
        "/api/v1/users/forgot-password",
        json={"email": "nonexistent@example.com"}
    )

    assert response.status_code == 200
    assert "reset link has been sent" in response.json()["detail"]
    assert not spy.called

async def test_reset_password_success(async_client: AsyncClient, confirmed_user: dict, db):
    # Create a valid reset token
    reset_token = create_reset_token(confirmed_user["id"])

    new_password = "newsecurepassword123"
    response = await async_client.post(
        "/api/v1/users/reset-password",
        json={
            "token": reset_token,
            "new_password": new_password
        }
    )

    assert response.status_code == 200
    assert "Password reset successfully" in response.json()["detail"]

    # Verify login with new password
    login_response = await async_client.post(
        "/api/v1/users/token",
        data={
            "username": confirmed_user["email"],
            "password": new_password
        }
    )
    assert login_response.status_code == 200

async def test_reset_password_invalid_token(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/users/reset-password",
        json={
            "token": "invalidtoken",
            "new_password": "newpassword123"
        }
    )
    assert response.status_code == 401

async def test_reset_password_expired_token(async_client: AsyncClient, confirmed_user: dict, mocker):
    mocker.patch("app.security.reset_token_expire_time", return_value=-1)
    reset_token = create_reset_token(confirmed_user["id"])

    response = await async_client.post(
        "/api/v1/users/reset-password",
        json={
            "token": reset_token,
            "new_password": "newpassword123"
        }
    )
    assert response.status_code == 401
    assert "Token has expired" in response.json()["detail"]

async def test_reset_password_too_short(async_client: AsyncClient, confirmed_user: dict):
    reset_token = create_reset_token(confirmed_user["id"])

    response = await async_client.post(
        "/api/v1/users/reset-password",
        json={
            "token": reset_token,
            "new_password": "short"
        }
    )
    assert response.status_code == 400
    assert "at least 8 characters" in response.json()["detail"]
