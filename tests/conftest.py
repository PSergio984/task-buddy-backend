"""Shared fixtures and test environment setup for the test suite."""

import asyncio
import os

os.environ["ENV_STATE"] = "test"
import tempfile
from collections.abc import AsyncGenerator, Generator
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Request, Response
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.database as app_db
import app.dependencies as app_deps
import app.tasks as app_tasks
from app.dependencies import get_db
from app.main import app
from app.models.base import Base
from app.models.user import User

# Unique file-backed database for this session
_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db_path = _db_file.name
_db_file.close()

TEST_DATABASE_URL = f"sqlite+aiosqlite:///{_db_path}"
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=20,
    max_overflow=30,
    pool_timeout=60,
)


# Cleanup the temp file after the session
@pytest.fixture(scope="session", autouse=True)
def cleanup_temp_db() -> Generator:
    yield
    try:
        asyncio.run(test_engine.dispose())
    except RuntimeError:
        pass
    try:
        os.remove(_db_path)
    except PermissionError:
        # On Windows, the file may still be locked by the engine disposal process
        pass


# Enable SQLite foreign key enforcement
@event.listens_for(test_engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


TestSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False
)

# Patch app.database globally
app_db.engine = test_engine
app_db.AsyncSessionLocal = TestSessionLocal
app_deps.AsyncSessionLocal = TestSessionLocal
app_tasks.AsyncSessionLocal = TestSessionLocal


# Override get_db dependency
async def override_get_db() -> AsyncGenerator:
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db

# Disable rate limiting for tests
app.state.limiter.enabled = False


# Mock Redis for security blacklist checks
@pytest.fixture(autouse=True)
def mock_redis_security(mocker: Any) -> Any:
    mocker.patch("app.security.is_token_blacklisted", return_value=False)
    mocker.patch("app.security.blacklist_token", return_value=None)

    # Global mock for get_redis_client to prevent connection attempts in tests
    mock_redis = mocker.MagicMock()
    mock_redis.keys = mocker.AsyncMock(return_value=[])
    mock_redis.delete = mocker.AsyncMock(return_value=0)
    mock_redis.setex = mocker.AsyncMock(return_value=True)
    mock_redis.exists = mocker.AsyncMock(return_value=False)
    mock_redis.get = mocker.AsyncMock(return_value=None)
    mock_redis.set = mocker.AsyncMock(return_value=True)
    # Cache invalidation index (audit #26): set_cached_data SADDs, invalidators
    # SMEMBERS/SREMs — all async so awaiting them in tests works.
    mock_redis.smembers = mocker.AsyncMock(return_value=set())
    mock_redis.sadd = mocker.AsyncMock(return_value=1)
    mock_redis.srem = mocker.AsyncMock(return_value=1)

    mocker.patch("app.security.get_redis_client", return_value=mock_redis)
    mocker.patch("app.libs.cache.get_redis_client", return_value=mock_redis)
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=mock_redis)


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

    from app.knowledge.retrieval import UserKnowledgeIndex

    UserKnowledgeIndex.clear_cache()

    async with TestSessionLocal() as session:
        yield session
        await session.rollback()  # Ensure nothing leaks


@pytest.fixture()
def client() -> Generator:
    yield TestClient(app)


@pytest.fixture()
async def async_client() -> AsyncGenerator:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver/") as ac:
        yield ac


@pytest.fixture()
async def registered_user(db: AsyncSession, async_client: AsyncClient) -> dict[str, Any]:
    user_data: dict[str, Any] = {
        "username": "testuser",
        "email": "testuser@example.com",
        "password": "testpassword",
    }
    response = await async_client.post("/api/v1/users/register", json=user_data)
    assert response.status_code == 201, f"User registration failed: {response.text}"

    stmt = select(User).where(User.email == user_data["email"])
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    assert user is not None, f"User {user_data['email']} was not found in DB after registration"
    user_data["id"] = user.id
    return user_data


@pytest.fixture()
async def confirmed_user(db: AsyncSession, registered_user: dict[str, Any]) -> dict[str, Any]:
    stmt = update(User).where(User.email == registered_user["email"]).values(confirmed=True)
    await db.execute(stmt)
    await db.commit()
    return registered_user


@pytest.fixture()
async def logged_in_token(async_client: AsyncClient, confirmed_user: dict) -> str:
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": confirmed_user["email"], "password": confirmed_user["password"]},
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    payload = response.json()
    token = cast(str, payload.get("access_token"))
    assert token, "Login response missing access_token"
    return token


@pytest.fixture(autouse=True)
def mock_httpx_client(mocker: Any) -> Any:
    """Mock httpx.AsyncClient to prevent real HTTP requests during tests."""
    mocked_client = mocker.patch("app.tasks.httpx.AsyncClient")
    mocked_smtp = mocker.patch("app.tasks.smtplib.SMTP")
    mocker.patch("app.tasks.config.MAIL_FROM_EMAIL", "test-sender@example.com")
    mocker.patch("app.tasks.config.MAIL_FROM_NAME", "Task Buddy")
    mocker.patch("app.tasks.config.MAIL_SMTP_HOST", "smtp-relay.brevo.com")
    mocker.patch("app.tasks.config.MAIL_SMTP_PORT", 587)
    mocker.patch("app.tasks.config.MAIL_SMTP_USERNAME", "test-user@smtp-brevo.com")
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


@pytest.fixture()
async def authenticated_async_client(
    async_client: AsyncClient, logged_in_token: str
) -> AsyncGenerator:
    async_client.headers.update({"Authorization": f"Bearer {logged_in_token}"})
    yield async_client
    if "Authorization" in async_client.headers:
        del async_client.headers["Authorization"]


@pytest.fixture(autouse=True)
def mock_embedder(mocker: Any) -> None:
    """Stub the local embedding model so tests never load sentence-transformers.

    The fake embedder mirrors the real contract: get_embedder() returns an
    object with .encode(texts, normalize_embeddings=True) producing a
    deterministic 384-dim vector per text (built from text length).
    """

    import hashlib

    import numpy as np  # noqa: PLC0415

    class _FakeEmbedder:
        def encode(self, texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
            if not texts:
                return np.empty((0, 384), dtype=np.float32)
            # Deterministic per-content vectors: different texts get different
            # directions (seeded by content hash), not just different lengths.
            vectors = []
            for text in texts:
                seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
                rng = np.random.default_rng(seed)
                vectors.append(rng.standard_normal(384).astype(np.float32))
            arr = np.array(vectors, dtype=np.float32)
            if normalize_embeddings:
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                arr = np.where(norms > 0, arr / norms, arr)
            return arr

    mocker.patch("app.knowledge.embeddings.get_embedder", return_value=_FakeEmbedder())
