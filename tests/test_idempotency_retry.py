"""Plan 03.9-03: retry logic and de-duplication verification tests.

Verifies the idempotency middleware against an in-memory Redis stand-in:
- a repeated request with the same key executes the handler exactly once,
- a 409 lock conflict becomes a successful retry once the lock clears,
- a 500 clears the lock so the user can retry and still create exactly one row,
- a crashed request leaves only a short-lived IN_PROGRESS marker, not a permanent block,
- a 429 rate-limit response clears the lock and is never cached,
- deterministic 4xx responses are cached and replayed without re-execution,
- independent keys are independent (no accidental cross-key de-duplication),
- lock and response-cache TTLs are set (30s / 1h).
"""

import json
import uuid
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.main import app
from app.models.project import Project

IN_PROGRESS_MARKER = json.dumps("IN_PROGRESS")
LOCK_TTL = 30
CACHE_TTL = 3600


class FakeRedis:
    """Minimal dict-backed stand-in for the AsyncRedis surface the middleware uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.deleted: list[str] = []
        self.set_calls: list[tuple[str, str, int | None, bool]] = []

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        self.set_calls.append((key, value, ex, nx))
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            self.deleted.append(key)
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed

    def expire(self, key: str) -> None:
        """Simulate TTL expiry by removing the key."""
        self.store.pop(key, None)


def _install_fake_redis(mocker: Any) -> FakeRedis:
    fake = FakeRedis()
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=fake)
    mocker.patch("app.security.get_redis_client", return_value=fake)
    return fake


def _scenario(mocker: Any, user_id: int | None = None) -> tuple[FakeRedis, str, str, dict[str, str]]:
    """Set up a fake Redis plus a fresh idempotency context.

    Returns (fake, key, cache_key, headers). The cache key matches the middleware's
    `idempotency:<user_id>:<key>` format so tests can seed/clear lock state.
    """
    fake = _install_fake_redis(mocker)
    key = str(uuid.uuid4())
    cache_key = f"idempotency:{user_id}:{key}"
    return fake, key, cache_key, {"X-Idempotency-Key": key}


async def _project_count(db: Any) -> int:
    result = await db.execute(select(func.count()).select_from(Project))
    return int(result.scalar_one())


@pytest.mark.anyio
async def test_same_key_executes_handler_once(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """A repeated request with the same key creates exactly one project row."""
    fake, _, _, headers = _scenario(mocker, 1)
    payload = {"name": f"Project {uuid.uuid4()}"}

    first = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert first.status_code == 201, f"First request failed: {first.text}"
    assert await _project_count(db) == 1

    second = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert second.status_code == 201, f"Replay failed: {second.text}"
    assert second.json() == first.json()
    assert await _project_count(db) == 1, "Handler executed more than once for the same key"

    # Lock is acquired with a 30s TTL; the cached response uses the 1h TTL
    lock_sets = [call for call in fake.set_calls if call[1] == IN_PROGRESS_MARKER]
    assert lock_sets, "Expected an IN_PROGRESS lock write"
    assert lock_sets[0][2] == LOCK_TTL
    cache_sets = [call for call in fake.set_calls if call[1] != IN_PROGRESS_MARKER]
    assert cache_sets, "Expected a cached response write"
    assert cache_sets[0][2] == CACHE_TTL


@pytest.mark.anyio
async def test_retry_after_409_conflict_succeeds(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any, confirmed_user: dict[str, Any]
) -> None:
    """A 409 from a held lock becomes a successful retry once the lock clears."""
    fake, _, cache_key, headers = _scenario(mocker, confirmed_user["id"])
    payload = {"name": f"Project {uuid.uuid4()}"}

    # Simulate a concurrent request holding the lock
    fake.store[cache_key] = IN_PROGRESS_MARKER

    blocked = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert blocked.status_code == 409
    assert await _project_count(db) == 0

    # The in-flight request finishes and clears the lock, then we retry
    fake.expire(cache_key)
    retried = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert retried.status_code == 201, f"Retry failed: {retried.text}"
    assert await _project_count(db) == 1


@pytest.mark.anyio
async def test_retry_after_500_creates_single_row(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """A 500 clears the lock so retrying with the same key succeeds exactly once."""
    fake, _, _, headers = _scenario(mocker, 1)
    payload = {"name": f"Project {uuid.uuid4()}"}

    with patch(
        "app.api.routers.project.project_crud.create_project",
        side_effect=Exception("Database error"),
    ):
        try:
            await authenticated_async_client.post(
                "/api/v1/projects/", json=payload, headers=headers
            )
            pytest.fail("Expected the patched CRUD failure to propagate")
        except Exception as exc:
            assert "Database error" in str(exc)

    assert len(fake.deleted) == 1, "Lock must be cleared on failure so the user can retry"

    retried = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert retried.status_code == 201, f"Retry after failure failed: {retried.text}"
    assert await _project_count(db) == 1


@pytest.mark.anyio
async def test_crashed_request_leaves_short_lived_lock(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any, confirmed_user: dict[str, Any]
) -> None:
    """An IN_PROGRESS marker blocks only while it lives; after TTL expiry the retry proceeds."""
    fake, _, cache_key, headers = _scenario(mocker, confirmed_user["id"])
    payload = {"name": f"Project {uuid.uuid4()}"}

    # A previous request crashed mid-flight, leaving only the 30s IN_PROGRESS marker
    fake.store[cache_key] = IN_PROGRESS_MARKER

    blocked = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert blocked.status_code == 409

    # 30s TTL elapses without a finished response
    fake.expire(cache_key)

    recovered = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert recovered.status_code == 201, f"Recovery retry failed: {recovered.text}"
    assert await _project_count(db) == 1


@pytest.mark.anyio
async def test_ratelimit_429_clears_lock_and_is_not_cached(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """A 429 response deletes the lock and is not cached, so a retry after reset succeeds."""
    fake, _, _, headers = _scenario(mocker, 1)
    payload = {"name": f"Project {uuid.uuid4()}"}

    limiter_enabled = app.state.limiter.enabled
    app.state.limiter.enabled = True
    app.state.limiter.reset()
    mocker.patch("slowapi.util.get_remote_address", return_value="1.2.3.4")
    try:
        # Exhaust the 10/minute limit on /api/v1/projects/ without an idempotency key
        for _ in range(10):
            response = await authenticated_async_client.post(
                "/api/v1/projects/", json={"name": f"Project {uuid.uuid4()}"}
            )
            assert response.status_code != 429

        limited = await authenticated_async_client.post(
            "/api/v1/projects/", json=payload, headers=headers
        )
        assert limited.status_code == 429

        # The lock was deleted and nothing was cached — the key is fully gone
        assert fake.deleted, "429 must delete the in-progress lock"
        assert not fake.store, "429 responses must not be cached"

        # Simulate the limit window elapsing, then retry with the same key
        app.state.limiter.reset()
        retried = await authenticated_async_client.post(
            "/api/v1/projects/", json=payload, headers=headers
        )
        assert retried.status_code == 201, f"Retry after rate limit failed: {retried.text}"
        assert await _project_count(db) == 11
    finally:
        app.state.limiter.reset()
        app.state.limiter.enabled = limiter_enabled


@pytest.mark.anyio
async def test_validation_error_cached_and_replayed(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """A deterministic 4xx response is cached and replayed without re-execution."""
    fake, _, _, headers = _scenario(mocker, 1)

    first = await authenticated_async_client.post("/api/v1/projects/", json={}, headers=headers)
    assert first.status_code == 422

    second = await authenticated_async_client.post("/api/v1/projects/", json={}, headers=headers)
    assert second.status_code == 422
    assert second.json() == first.json()

    # One cached payload — the handler never ran for the replay
    assert len(fake.store) == 1
    assert await _project_count(db) == 0


@pytest.mark.anyio
async def test_distinct_keys_are_independent(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """Different idempotency keys create independent resources."""
    _install_fake_redis(mocker)

    for i in range(2):
        response = await authenticated_async_client.post(
            "/api/v1/projects/",
            json={"name": f"Project {uuid.uuid4()}-{i}"},
            headers={"X-Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 201

    assert await _project_count(db) == 2
