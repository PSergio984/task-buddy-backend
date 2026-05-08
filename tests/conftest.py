import pytest

from collections.abc import AsyncGenerator, Generator
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, Mock

from app.main import app
from app.models.base import Base
from app.database import engine, AsyncSessionLocal
from app.models.user import User
from app.models.task import Task, SubTask
from app.models.tag import Tag
from sqlalchemy import delete

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture()
async def db() -> AsyncGenerator:
    # Use sync engine for schema operations (simpler for SQLite tests)
    # But wait, we are using create_async_engine. 
    # For schema drop/create we should use async engine too if possible, 
    # or just use the sync-style metadata.create_all with engine.connect() if it's a sync engine.
    # Actually, SQLAlchemy 2.0 with AsyncEngine needs run_sync.
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSessionLocal() as session:
        # Clear child tables before parents to respect FK constraints.
        # This is optional if we just drop/create each time, but good practice.
        yield session
        await session.rollback() # Ensure nothing leaks


@pytest.fixture()
def client() -> Generator:
    yield TestClient(app)


@pytest.fixture(scope="session")
async def async_client() -> AsyncGenerator:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver/") as ac:
        yield ac


@pytest.fixture()
async def registered_user(db: AsyncSession, async_client: AsyncClient) -> dict:
    user_data = {
        "username": "testuser",
        "email": "testuser@example.com",
        "password": "testpassword",
    }
    response = await async_client.post("/api/v1/users/register", json=user_data)

    assert response.status_code == 201, (
        f"Registration failed with status {response.status_code}: {response.json()}"
    )

    from sqlalchemy import select
    stmt = select(User).where(User.email == user_data["email"])
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    assert user is not None, (
        f"User not found in database after registration for email: {user_data['email']}"
    )

    user_data["id"] = user.id
    return user_data


@pytest.fixture()
async def confirmed_user(db: AsyncSession, registered_user: dict) -> dict:
    from sqlalchemy import update
    stmt = (
        update(User).where(User.email == registered_user["email"]).values(confirmed=True)
    )
    await db.execute(stmt)
    await db.commit()
    return registered_user


@pytest.fixture()
async def logged_in_token(async_client: AsyncClient, confirmed_user: dict) -> str:
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": confirmed_user["email"], "password": confirmed_user["password"]},
    )
    assert response.status_code == 200, (
        f"Login failed with status {response.status_code}: {response.json()}"
    )

    payload = response.json()
    token = payload.get("access_token")
    assert isinstance(token, str) and token, (
        f"Login response did not include a valid access_token: {payload}"
    )
    return token


@pytest.fixture(autouse=True)
def mock_httpx_client(mocker):
    """Mock httpx.AsyncClient to prevent real HTTP requests during tests."""
    mocked_client = mocker.patch("app.tasks.httpx.AsyncClient")
    mocked_smtp = mocker.patch("app.tasks.smtplib.SMTP")
    mocker.patch("app.tasks.config.MAIL_FROM_EMAIL", "test-sender@example.com")
    mocker.patch("app.tasks.config.MAIL_FROM_NAME", "Task Buddy")
    mocker.patch("app.tasks.config.MAIL_SMTP_HOST", "smtp-relay.brevo.com")
    mocker.patch("app.tasks.config.MAIL_SMTP_PORT", 587)
    mocker.patch("app.tasks.config.MAIL_SMTP_USERNAME", "9d9828001@smtp-brevo.com")
    mocker.patch("app.tasks.config.MAIL_SMTP_PASSWORD", "test-smtp-password")
    mocker.patch("app.tasks.config.MAIL_SMTP_USE_TLS", True)

    mocked_async_client = AsyncMock()

    response = Response(200, content="", request=Request("POST", "//"))

    mocked_async_client.post = AsyncMock(return_value=response)
    mocked_client.return_value.__aenter__.return_value = mocked_async_client

    smtp_client = mocked_smtp.return_value.__enter__.return_value
    smtp_client.starttls.return_value = None
    smtp_client.login.return_value = None
    smtp_client.send_message.return_value = None

    mocked_async_client.smtp = mocked_smtp
    mocked_async_client.smtp_client = smtp_client
    return mocked_async_client
