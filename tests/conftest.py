import pytest
from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.main import app
from app.models.base import Base
from app.models.user import User

# Force SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=NullPool
)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Patch app.database globally
import app.database as app_db
app_db.engine = test_engine
app_db.AsyncSessionLocal = TestSessionLocal

# Override get_db dependency
async def override_get_db() -> AsyncGenerator:
    async with TestSessionLocal() as session:
        yield session

from app.dependencies import get_db
app.dependency_overrides[get_db] = override_get_db

# Disable rate limiting for tests
app.state.limiter.enabled = False

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture(scope="session", autouse=True)
async def setup_db_schema():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await test_engine.dispose()

@pytest.fixture()
async def db() -> AsyncGenerator:
    # Clear all data before each test
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

    async with TestSessionLocal() as session:
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
    
    from sqlalchemy import select
    stmt = select(User).where(User.email == user_data["email"])
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        user_data["id"] = str(user.id)
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
    payload = response.json()
    token = payload.get("access_token", "")
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
