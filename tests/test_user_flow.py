import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_forgot_password_success(async_client: AsyncClient, db, mocker):
    # Mock background tasks to avoid sending actual emails
    mocker.patch("app.tasks.send_password_reset_email")

    # Create a user
    from app.crud import user as user_crud
    from app.schemas.user import UserCreateRequest

    user_in = UserCreateRequest(
        username="forgotuser",
        email="forgot@example.com",
        password="testpassword"
    )
    await user_crud.create_user(db, user_in=user_in, hashed_password="hashed")
    await db.commit()

    response = await async_client.post(
        "/api/v1/users/forgot-password",
        json={"email": "forgot@example.com"}
    )

    assert response.status_code == 200
    assert "reset link has been sent" in response.json()["detail"]

@pytest.mark.asyncio
async def test_forgot_password_nonexistent_user(async_client: AsyncClient, mocker):
    mocker.patch("app.tasks.send_password_reset_email")

    response = await async_client.post(
        "/api/v1/users/forgot-password",
        json={"email": "nonexistent@example.com"}
    )

    # Should still return 200 to avoid enumeration
    assert response.status_code == 200
    assert "reset link has been sent" in response.json()["detail"]
