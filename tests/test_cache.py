"""Tests for the Redis-backed cache layer."""

from datetime import datetime
from typing import Any

import pytest

from app.libs.cache import delete_cached_user_keys, get_cache_key, get_cached_data, set_cached_data
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
        updated_at=datetime(2026, 5, 17, 12, 0, 0),
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
            updated_at=datetime(2026, 5, 17, 12, 0, 0),
        ),
        Task(
            id=102,
            title="Task 102",
            completed=True,
            priority="HIGH",
            user_id=1,
            created_at=datetime(2026, 5, 17, 13, 0, 0),
            updated_at=datetime(2026, 5, 17, 13, 0, 0),
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


def _mock_redis_with_index(mocker: Any) -> tuple[Any, dict[str, Any]]:
    """Mock redis with a store plus an SADD-tracked per-user key index.

    Returns (mock_redis, store) — mirroring the production semantics of
    set_cached_data + delete_cached_user_keys (audit #26: no KEYS scan).
    """
    mock_redis = mocker.MagicMock()
    store: dict[str, Any] = {}

    async def mock_setex(key, expire, value):
        store[key] = value
        return True

    async def mock_get(key):
        return store.get(key)

    async def mock_sadd(key, member):
        store.setdefault(key, set()).add(member)
        return 1

    async def mock_smembers(key):
        return set(store.get(key, set()))

    async def mock_delete(*keys):
        for k in keys:
            store.pop(k, None)
        return len(keys)

    async def mock_srem(key, *members):
        index = store.setdefault(key, set())
        for m in members:
            index.discard(m)
        return len(members)

    mock_redis.setex = mock_setex
    mock_redis.get = mock_get
    mock_redis.sadd = mock_sadd
    mock_redis.smembers = mock_smembers
    mock_redis.delete = mock_delete
    mock_redis.srem = mock_srem
    mocker.patch("app.libs.cache.get_redis_client", return_value=mock_redis)
    return mock_redis, store


@pytest.mark.anyio
async def test_set_cached_data_tracks_key_in_user_index(mocker: Any) -> None:
    """Generated keys must be added to the user's invalidation index."""
    _, store = _mock_redis_with_index(mocker)

    cache_key = get_cache_key("tasks_list", 42, completed=True, limit=100)
    await set_cached_data(cache_key, {"title": "x"})

    index_key = "cache:user:42:keys"
    assert index_key in store
    assert cache_key in store[index_key]


@pytest.mark.anyio
async def test_delete_cached_user_keys_filters_by_prefix(mocker: Any) -> None:
    """Invalidation must delete only the matching keys, and prune the index."""
    _, store = _mock_redis_with_index(mocker)

    task_key = get_cache_key("task_detail", 42, task_id=7, with_subtasks=True)
    list_key = get_cache_key("tasks_list", 42, completed=True, limit=100)
    other_user_key = get_cache_key("tasks_list", 99, limit=100)
    await set_cached_data(task_key, {"a": 1})
    await set_cached_data(list_key, {"b": 2})
    await set_cached_data(other_user_key, {"c": 3})

    await delete_cached_user_keys(42, "cache:tasks_list:42:", "cache:task_detail:42:task_id=7")

    assert list_key not in store
    assert task_key not in store
    assert other_user_key in store  # other users untouched
    index = store["cache:user:42:keys"]
    assert list_key not in index
    assert task_key not in index
    assert "cache:user:99:keys" in store  # other index untouched


@pytest.mark.anyio
async def test_delete_cached_user_keys_without_index_is_noop(mocker: Any) -> None:
    """No index set (or redis down) must not raise."""
    _, store = _mock_redis_with_index(mocker)
    await delete_cached_user_keys(42, "cache:tasks_list:42:")
    assert store == {}
