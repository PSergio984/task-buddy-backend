"""Tests for the Redis-backed cache layer."""

from datetime import datetime
from typing import Any

import pytest

from app.libs.cache import get_cached_data, set_cached_data
from app.models.task import Task
from app.schemas.task import TaskCreateResponse


@pytest.mark.anyio
async def test_cache_primitive_data(mocker: Any) -> None:
    """Test caching primitive python types."""
    # Setup mock Redis client
    mock_redis = mocker.MagicMock()
    stored_data = {}

    async def mock_setex(key, expire, value):
        stored_data[key] = value
        return True

    async def mock_get(key):
        return stored_data.get(key)

    mock_redis.setex = mock_setex
    mock_redis.get = mock_get
    mocker.patch("app.libs.cache.get_redis_client", return_value=mock_redis)

    cache_key = "test_key_primitive"
    test_data = {"hello": "world", "number": 42}

    # Store
    await set_cached_data(cache_key, test_data)

    # Retrieve
    retrieved = await get_cached_data(cache_key, dict)
    assert retrieved == test_data


@pytest.mark.anyio
async def test_cache_sqlalchemy_model(mocker: Any) -> None:
    """Test that SQLAlchemy models are serialized using jsonable_encoder without causing PydanticSerializationError."""
    mock_redis = mocker.MagicMock()
    stored_data = {}

    async def mock_setex(key, expire, value):
        stored_data[key] = value
        return True

    async def mock_get(key):
        return stored_data.get(key)

    mock_redis.setex = mock_setex
    mock_redis.get = mock_get
    mocker.patch("app.libs.cache.get_redis_client", return_value=mock_redis)

    cache_key = "test_key_sqlalchemy"

    # Create dummy SQLAlchemy Task model
    dummy_task = Task(
        id=99,
        title="SQLAlchemy Cache Task",
        description="Testing caching direct database models",
        completed=False,
        priority="MEDIUM",
        user_id=1,
        created_at=datetime(2026, 5, 17, 12, 0, 0),
    )

    # Try storing the SQLAlchemy model directly.
    # Previously, this would raise PydanticSerializationError.
    await set_cached_data(cache_key, dummy_task)

    # Verify something was cached
    assert cache_key in stored_data
    assert b"SQLAlchemy Cache Task" in stored_data[cache_key]

    # Retrieve and deserialize using the corresponding Pydantic schema
    retrieved = await get_cached_data(cache_key, TaskCreateResponse)
    assert retrieved is not None
    assert retrieved.id == 99
    assert retrieved.title == "SQLAlchemy Cache Task"
    assert retrieved.description == "Testing caching direct database models"
    assert retrieved.completed is False
    assert retrieved.user_id == 1
    assert retrieved.created_at == datetime(2026, 5, 17, 12, 0, 0)


@pytest.mark.anyio
async def test_cache_list_of_sqlalchemy_models(mocker: Any) -> None:
    """Test that a list of SQLAlchemy models can be cleanly cached and retrieved."""
    mock_redis = mocker.MagicMock()
    stored_data = {}

    async def mock_setex(key, expire, value):
        stored_data[key] = value
        return True

    async def mock_get(key):
        return stored_data.get(key)

    mock_redis.setex = mock_setex
    mock_redis.get = mock_get
    mocker.patch("app.libs.cache.get_redis_client", return_value=mock_redis)

    cache_key = "test_key_sqlalchemy_list"

    tasks = [
        Task(
            id=101,
            title="Task 101",
            completed=False,
            priority="LOW",
            user_id=1,
            created_at=datetime(2026, 5, 17, 12, 0, 0),
        ),
        Task(
            id=102,
            title="Task 102",
            completed=True,
            priority="HIGH",
            user_id=1,
            created_at=datetime(2026, 5, 17, 13, 0, 0),
        ),
    ]

    # Store
    await set_cached_data(cache_key, tasks)

    # Verify cache content exists and contains serialized tasks
    assert cache_key in stored_data

    # Retrieve and deserialize
    retrieved = await get_cached_data(cache_key, list[TaskCreateResponse])
    assert retrieved is not None
    assert len(retrieved) == 2
    assert retrieved[0].id == 101
    assert retrieved[0].title == "Task 101"
    assert retrieved[1].id == 102
    assert retrieved[1].title == "Task 102"
    assert retrieved[1].completed is True
