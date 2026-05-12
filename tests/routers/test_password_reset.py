from httpx import AsyncClient

from app.security import create_reset_token


async def test_forgot_password_success(async_client: AsyncClient, confirmed_user: dict, mocker):
    mock_delay = mocker.patch("app.tasks.send_password_reset_email.delay")

    response = await async_client.post(
        "/api/v1/users/forgot-password/",
        json={"email": confirmed_user["email"]}
    )

    assert response.status_code == 200
    assert "reset link has been sent" in response.json()["detail"]
    assert mock_delay.called

    # Check reset URL in background task call
    reset_url = mock_delay.call_args[1]["reset_url"]
    assert "/reset-password/" in reset_url

async def test_forgot_password_user_not_found(async_client: AsyncClient, mocker):
    mock_delay = mocker.patch("app.tasks.send_password_reset_email.delay")

    response = await async_client.post(
        "/api/v1/users/forgot-password/",
        json={"email": "nonexistent@example.com"}
    )

    assert response.status_code == 200
    assert "reset link has been sent" in response.json()["detail"]
    assert not mock_delay.called

async def test_reset_password_success(async_client: AsyncClient, confirmed_user: dict, db, mocker):
    # Mock the confirmation email task
    mock_delay = mocker.patch("app.tasks.send_password_changed_confirmation.delay")

    # Create a valid reset token
    reset_token = create_reset_token(confirmed_user["id"])

    new_password = "newsecurepassword123"
    response = await async_client.post(
        "/api/v1/users/reset-password/",
        json={
            "token": reset_token,
            "new_password": new_password
        }
    )

    assert response.status_code == 200
    assert "Password reset successfully" in response.json()["detail"]
    assert mock_delay.called

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
        "/api/v1/users/reset-password/",
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
        "/api/v1/users/reset-password/",
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
        "/api/v1/users/reset-password/",
        json={
            "token": reset_token,
            "new_password": "short"
        }
    )
    assert response.status_code == 400
    assert "at least 8 characters" in response.json()["detail"]
