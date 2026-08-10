"""Plan 03.9-03: retry logic and de-duplication verification tests.

Verifies the idempotency middleware against an in-memory Redis stand-in:
- a repeated request with the same key executes the handler exactly once,
- a 409 lock conflict is served the in-flight request's cached response once it finishes,
- a 500 clears the lock so the user can retry and still create exactly one row,
- a crashed request leaves only a short-lived IN_PROGRESS marker, not a permanent block,
- a lost SET NX race returns 409 without executing the handler,
- a lost SET NX race whose finisher completed is served the cached response on re-check,
- a 429 rate-limit response clears the lock and is never cached,
- deterministic 4xx responses are cached and replayed without re-execution,
- a changed body under the same key still replays the original response,
- once the 1h cached response expires, the same key re-executes — with a fresh payload
  it succeeds, with the original body it hits the app's unique-name domain guard,
- independent keys are independent (no accidental cross-key de-duplication),
- the lock is atomic (SET NX), has a 30s TTL, and is replaced by the 1h cached response on success.
"""

import json
import uuid
from typing import Any, NamedTuple
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.main import app
from app.models.project import Project

IN_PROGRESS_MARKER = json.dumps("IN_PROGRESS")
LOCK_TTL = 30
CACHE_TTL = 3600


class SetCall(NamedTuple):
    key: str
    value: str
    ex: int | None
    nx: bool


class FakeRedis:
    """Minimal dict-backed stand-in for the AsyncRedis surface the middleware uses."""

    def __init__(self) -> None:
        """Start with an empty store and no recorded calls."""
        self.store: dict[str, str] = {}
        self.deleted: list[str] = []
        self.set_calls: list[SetCall] = []
        # Consume-once: the next SET NX fails as if the key appeared between GET and SET,
        # then -- if replay_on_recheck is set -- subsequent GETs serve it (the "finisher"
        # completed mid-race).
        self.block_next_nx: bool = False
        self.replay_on_recheck: str | None = None
        self._recheck_armed = False

    async def get(self, key: str) -> Any:
        """Return the stored value, or the recheck replay once a SET NX race was lost."""
        if self._recheck_armed and self.replay_on_recheck is not None:
            return self.replay_on_recheck
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        """Store a value (with SET NX semantics), recording the call and optional lock race."""
        self.set_calls.append(SetCall(key, value, ex, nx))
        if nx and (key in self.store or self.block_next_nx):
            self.block_next_nx = False
            self._recheck_armed = True
            return False
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        """Remove the given keys, recording every deletion attempt."""
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
    """Patch both Redis access points with a shared FakeRedis instance."""
    fake = FakeRedis()
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=fake)
    mocker.patch("app.security.get_redis_client", return_value=fake)
    return fake


def _cache_key(user_id: Any, key: str) -> str:
    """Mirror the middleware's `idempotency:<user_id>:<key>` format for seeding lock state."""
    return f"idempotency:{user_id}:{key}"


class Scenario(NamedTuple):
    fake: FakeRedis
    key: str
    headers: dict[str, str]


def _scenario(mocker: Any) -> Scenario:
    """Set up a fake Redis plus a fresh idempotency key and headers."""
    fake = _install_fake_redis(mocker)
    key = str(uuid.uuid4())
    return Scenario(fake, key, {"X-Idempotency-Key": key})


def _payload() -> dict[str, str]:
    """Return a unique, valid project creation payload."""
    return {"name": f"Project {uuid.uuid4()}"}


def _cached_finisher_response(payload: dict[str, str]) -> dict[str, Any]:
    """Mirror the cache payload `_handle_response` stores for a successful finisher."""
    return {
        "status_code": 201,
        "body": json.dumps({"id": 1, "name": payload["name"]}),
        "headers": {"content-type": "application/json"},
        "media_type": "application/json",
    }


def _fresh_headers() -> dict[str, str]:
    """Return headers carrying a brand-new idempotency key."""
    return {"X-Idempotency-Key": str(uuid.uuid4())}


def _replayed_headers(headers: Any) -> dict[str, str]:
    """Headers as replayed by the cache, minus the per-request correlation id.

    x-request-id is generated by the correlation-id middleware outside the idempotency
    middleware, so it legitimately differs between the original request and the replay.
    """
    return {key.lower(): value for key, value in headers.items() if key.lower() != "x-request-id"}


async def _project_count(db: Any) -> int:
    """Count the projects persisted in the test database."""
    result = await db.execute(select(func.count()).select_from(Project))
    return int(result.scalar_one())


@pytest.mark.anyio
async def test_same_key_executes_handler_once(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """A repeated request with the same key creates exactly one project row."""
    fake, _, headers = _scenario(mocker)
    payload = _payload()

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
    assert second.content == first.content
    assert _replayed_headers(second.headers) == _replayed_headers(first.headers)
    assert await _project_count(db) == 1, "Handler executed more than once for the same key"

    # The lock write is atomic (SET NX) with a 30s TTL; the cached response uses the 1h TTL
    lock_sets = [call for call in fake.set_calls if call.value == IN_PROGRESS_MARKER]
    assert lock_sets, "Expected an IN_PROGRESS lock write"
    lock = lock_sets[-1]
    assert lock.ex == LOCK_TTL, "Lock TTL must be 30s"
    assert lock.nx is True, "Lock must be acquired with SET NX"

    cache_sets = [call for call in fake.set_calls if call.value != IN_PROGRESS_MARKER]
    assert cache_sets, "Expected a cached response write"
    assert cache_sets[-1].ex == CACHE_TTL

    # Success-path cleanup: the lock marker is gone, replaced by the cached response
    cached = json.loads(fake.store[lock.key])
    assert cached != json.loads(IN_PROGRESS_MARKER), "Lock marker must be replaced on success"
    assert cached["status_code"] == 201


@pytest.mark.anyio
async def test_retry_after_409_conflict_succeeds(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any, confirmed_user: dict[str, Any]
) -> None:
    """A 409 from a held lock is served the in-flight request's cached response once it finishes."""
    fake, key, headers = _scenario(mocker)
    cache_key = _cache_key(confirmed_user["id"], key)
    payload = _payload()

    # Simulate a concurrent request holding the lock
    fake.store[cache_key] = IN_PROGRESS_MARKER

    blocked = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert blocked.status_code == 409
    assert await _project_count(db) == 0

    # The in-flight request finishes: the middleware replaced the lock with the cached
    # response (the same shape _handle_response stores on success). The retry is served
    # that response without re-running the handler — no row is ever created by the retry.
    fake.store[cache_key] = json.dumps(_cached_finisher_response(payload))

    retried = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert retried.status_code == 201, f"Retry failed: {retried.text}"
    assert retried.json()["name"] == payload["name"]
    # Replayed from cache — the handler must NOT have run again
    assert await _project_count(db) == 0


@pytest.mark.anyio
async def test_same_key_different_payload_replays_original(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """A changed body under the same key still returns the original cached response."""
    fake, _, headers = _scenario(mocker)
    payload = _payload()

    first = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert first.status_code == 201
    assert await _project_count(db) == 1

    # The cache key is user-scoped and body-independent — the middleware never reads
    # the request body, so a retry with a different payload must not re-execute
    second = await authenticated_async_client.post(
        "/api/v1/projects/", json=_payload(), headers=headers
    )
    assert second.status_code == 201
    assert second.json() == first.json(), "Replay must return the original response"
    assert await _project_count(db) == 1, "Changed body must not re-execute the handler"


@pytest.mark.anyio
async def test_cached_response_expiry_allows_re_execution(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any, confirmed_user: dict[str, Any]
) -> None:
    """Once the 1h cached response expires, the same key re-executes and creates a new row."""
    fake, key, headers = _scenario(mocker)
    cache_key = _cache_key(confirmed_user["id"], key)
    payload = _payload()

    first = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert first.status_code == 201
    assert await _project_count(db) == 1

    # 1h TTL elapses without any request — the cached response is gone
    fake.expire(cache_key)

    # The key is reusable for a new request; a fresh payload avoids the app's own
    # unique (user_id, name) constraint, which is a domain guard, not idempotency
    second_payload = _payload()
    second = await authenticated_async_client.post(
        "/api/v1/projects/", json=second_payload, headers=headers
    )
    assert second.status_code == 201, f"Re-execution failed: {second.text}"
    assert second.json()["name"] == second_payload["name"]
    assert await _project_count(db) == 2, "Cache expiry must allow re-execution"


@pytest.mark.anyio
async def test_same_payload_retry_after_expiry_hits_domain_guard(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any, confirmed_user: dict[str, Any]
) -> None:
    """After the 1h window, retrying the original body re-executes into the app's
    unique (user_id, name) guard — the domain, not idempotency, rejects the duplicate."""
    fake, key, headers = _scenario(mocker)
    cache_key = _cache_key(confirmed_user["id"], key)
    payload = _payload()

    first = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert first.status_code == 201
    assert await _project_count(db) == 1

    # 1h TTL elapses — the cached response is gone, so the retry reaches the handler
    fake.expire(cache_key)

    retried = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert retried.status_code == 400
    assert "already exists" in retried.text
    assert await _project_count(db) == 1, "No duplicate row — the domain guard held"


@pytest.mark.anyio
async def test_retry_after_500_creates_single_row(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any, confirmed_user: dict[str, Any]
) -> None:
    """A 500 clears the lock so retrying with the same key succeeds exactly once."""
    fake, key, headers = _scenario(mocker)
    lock_key = _cache_key(confirmed_user["id"], key)
    payload = _payload()

    with patch(
        "app.api.routers.project.project_crud.create_project",
        side_effect=Exception("Database error"),
    ):
        # raise_app_exceptions=False so the client observes the real 500 response
        # instead of the re-raised exception
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver/") as client:
            client.headers.update(authenticated_async_client.headers)
            failed = await client.post("/api/v1/projects/", json=payload, headers=headers)
            assert failed.status_code == 500

    assert fake.deleted == [lock_key], "The lock must be cleared on failure so the user can retry"

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
    fake, key, headers = _scenario(mocker)
    cache_key = _cache_key(confirmed_user["id"], key)
    payload = _payload()

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
async def test_set_nx_conflict_returns_409(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """If the lock appears between the cache check and SET NX, the request gets a 409."""
    fake, _, headers = _scenario(mocker)
    payload = _payload()
    fake.block_next_nx = True  # another request acquired the lock just after our GET

    response = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert response.status_code == 409
    assert await _project_count(db) == 0

    # The lost race was decided by an atomic SET NX — not by any non-atomic check
    lock_sets = [call for call in fake.set_calls if call.value == IN_PROGRESS_MARKER]
    assert lock_sets, "Expected an IN_PROGRESS lock attempt"
    assert lock_sets[-1].nx is True, "Lock must be attempted with SET NX"


@pytest.mark.anyio
async def test_set_nx_conflict_replays_finished_response(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """If the in-flight request finishes between the lock failure and the re-check,
    the retry is served its cached response instead of a 409."""
    fake, _, headers = _scenario(mocker)
    payload = _payload()
    fake.block_next_nx = True
    fake.replay_on_recheck = json.dumps(_cached_finisher_response(payload))

    response = await authenticated_async_client.post(
        "/api/v1/projects/", json=payload, headers=headers
    )
    assert response.status_code == 201
    assert response.json()["name"] == payload["name"]
    assert await _project_count(db) == 0, "Replay must not re-run the handler"


@pytest.mark.anyio
async def test_ratelimit_429_clears_lock_and_is_not_cached(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any, confirmed_user: dict[str, Any]
) -> None:
    """A 429 response deletes the lock and is not cached, so a retry after reset succeeds."""
    fake, key, headers = _scenario(mocker)
    lock_key = _cache_key(confirmed_user["id"], key)
    payload = _payload()

    mocker.patch.object(app.state.limiter, "enabled", True)
    app.state.limiter.reset()
    mocker.patch("slowapi.util.get_remote_address", return_value="1.2.3.4")
    try:
        # Exhaust the 10/minute limit on /api/v1/projects/ without an idempotency key
        for _ in range(10):
            response = await authenticated_async_client.post("/api/v1/projects/", json=_payload())
            assert response.status_code != 429

        limited = await authenticated_async_client.post(
            "/api/v1/projects/", json=payload, headers=headers
        )
        assert limited.status_code == 429

        # The lock was deleted and nothing was cached — the key is fully gone
        assert fake.deleted == [lock_key], "429 must delete exactly the in-progress lock"
        assert not fake.store, "429 responses must not be cached"

        # Simulate the limit window elapsing, then retry with the same key
        app.state.limiter.reset()
        retried = await authenticated_async_client.post(
            "/api/v1/projects/", json=payload, headers=headers
        )
        assert retried.status_code == 201, f"Retry after rate limit failed: {retried.text}"
        # 10 limit-exhaustion attempts + 1 successful retry
        assert await _project_count(db) == 11
    finally:
        app.state.limiter.reset()


@pytest.mark.anyio
async def test_validation_error_cached_and_replayed(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """A deterministic 4xx response is cached and replayed without re-execution."""
    fake, _, headers = _scenario(mocker)

    first = await authenticated_async_client.post("/api/v1/projects/", json={}, headers=headers)
    assert first.status_code == 422

    second = await authenticated_async_client.post("/api/v1/projects/", json={}, headers=headers)
    assert second.status_code == 422
    assert second.json() == first.json()
    assert _replayed_headers(second.headers) == _replayed_headers(first.headers)

    # One cached payload — the handler never ran for the replay
    assert len(fake.store) == 1
    assert await _project_count(db) == 0


@pytest.mark.anyio
async def test_distinct_keys_are_independent(
    authenticated_async_client: AsyncClient, db: Any, mocker: Any
) -> None:
    """Different idempotency keys create independent resources."""
    _install_fake_redis(mocker)

    for _ in range(2):
        response = await authenticated_async_client.post(
            "/api/v1/projects/", json=_payload(), headers=_fresh_headers()
        )
        assert response.status_code == 201

    assert await _project_count(db) == 2
