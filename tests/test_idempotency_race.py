"""Race regression: idempotency duplicate keys are delivered exactly-once.

Pass condition (RELI-03 race target 2):
    K concurrent POSTs sharing one X-Idempotency-Key execute the downstream
    handler EXACTLY once (crud invocation count == 1). Every duplicate
    delivery either (a) receives the winner's response replayed from the
    response cache with IDENTICAL status_code AND IDENTICAL parsed body, or
    (b) arrives while the winner is still executing and receives the
    deterministic 409 "already in progress" rejection (byte-identical body
    across all such rejections). In both branches the handler never runs a
    second time and no phantom row is created. A subsequent request carrying
    a DIFFERENT idempotency key succeeds independently (no key bleed).
    Re-running this suite reproduces the outcome deterministically.

Note on the plan's "every response identical" wording: against the real
middleware, simultaneous losers that fail the SET-NX lock while the winner is
mid-handler get 409 (the middleware checks the cache once more immediately,
with no retry loop); byte-identical replay applies to every delivery that
lands after the winner caches its response (asserted here over a full K-way
replay wave). The exactly-once guarantee itself is timing-independent.

Limitation: asyncio.gather over httpx ASGITransport exercises await-point
interleaving only (single event loop; aiosqlite funnels writes through one
connection queue). The logic under test is dialect-independent; the Postgres
CI leg covers DDL separately. No artificial delays or wall-clock/timing
assertions are used anywhere in this file.
"""

import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

import app.api.routers.project as project_router

K_CONCURRENT = 5


class _FakeSetNxRedis:
    """In-memory Redis fake reproducing SET-NX first-writer-wins semantics.

    Fidelity contract (threat T-04-09): ``set(..., nx=True)`` succeeds iff the
    key is absent (atomic within the single event loop); plain ``set``
    overwrites (the response-cache write); ``get``/``delete`` behave like the
    real client. Without first-writer-wins the test would prove nothing.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx:
            if key in self._store:
                return False
            self._store[key] = value
            return True
        self._store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0


@pytest.mark.anyio
async def test_idempotent_duplicate_key_exactly_once_under_gather(
    authenticated_async_client: AsyncClient, mocker: Any
) -> None:
    """K same-key gather: handler runs once; duplicates reject or replay; no bleed."""
    # Real SET-NX fake at the middleware's import site (overrides the coarse
    # autouse conftest mock for the duration of this test).
    fake_redis = _FakeSetNxRedis()
    mocker.patch("app.middleware.idempotency.get_redis_client", return_value=fake_redis)

    # Counting wrapper around ONE downstream crud function so handler
    # invocations are observable while keeping the real DB behavior.
    real_create_project = project_router.project_crud.create_project
    invocations: list[int] = []

    async def counting_create_project(*args: Any, **kwargs: Any) -> Any:
        invocations.append(1)
        return await real_create_project(*args, **kwargs)

    mocker.patch.object(
        project_router.project_crud,
        "create_project",
        side_effect=counting_create_project,
    )

    idempotency_key = str(uuid.uuid4())
    headers = {"X-Idempotency-Key": idempotency_key}

    # --- Phase A: true K-way race on one key -------------------------------
    responses = await asyncio.gather(
        *[
            authenticated_async_client.post(
                "/api/v1/projects/", json={"name": "P1"}, headers=headers
            )
            for _ in range(K_CONCURRENT)
        ],
        return_exceptions=True,
    )
    assert not any(isinstance(r, BaseException) for r in responses), (
        f"Exceptions escaped the gather: {responses!r}"
    )
    http_responses = [r for r in responses if not isinstance(r, BaseException)]

    # Pass condition 1: downstream handler executed EXACTLY once.
    assert len(invocations) == 1, (
        f"Handler invoked {len(invocations)} times under {K_CONCURRENT}-way same-key gather"
    )

    # Pass condition 2: winners are byte-identical successes; in-flight
    # duplicates are uniform 409 rejections. Nothing else may appear.
    created = [r for r in http_responses if r.status_code == 201]
    rejected = [r for r in http_responses if r.status_code == 409]
    assert len(created) >= 1, f"No request succeeded: {[r.status_code for r in http_responses]}"
    assert len(created) + len(rejected) == K_CONCURRENT, (
        f"Unexpected statuses: {[r.status_code for r in http_responses]}"
    )
    winner = created[0]
    for resp in created[1:]:
        assert resp.status_code == winner.status_code
        assert resp.json() == winner.json()
    for resp in rejected:
        assert resp.json() == {"detail": "Request already in progress with this idempotency key."}
    assert winner.json()["name"] == "P1"

    # --- Phase B: post-completion duplicate wave replays byte-identically ---
    replay_responses = await asyncio.gather(
        *[
            authenticated_async_client.post(
                "/api/v1/projects/", json={"name": "P1"}, headers=headers
            )
            for _ in range(K_CONCURRENT)
        ]
    )
    for resp in replay_responses:
        assert resp.status_code == winner.status_code, (
            f"Replay status drifted: {resp.status_code} vs {winner.status_code}"
        )
        assert resp.json() == winner.json(), "Cached replay body differs from winner payload"

    # --- Phase C: distinct-key control proves no key bleed ------------------
    control_resp = await authenticated_async_client.post(
        "/api/v1/projects/",
        json={"name": "P2"},
        headers={"X-Idempotency-Key": str(uuid.uuid4())},
    )
    assert control_resp.status_code == 201, f"Control request failed: {control_resp.text}"
    assert control_resp.json()["id"] != winner.json()["id"]

    # Exactly two projects exist: the single winner execution + the control.
    listing = await authenticated_async_client.get("/api/v1/projects/")
    assert listing.status_code == 200
    names = sorted(p["name"] for p in listing.json())
    assert names == ["P1", "P2"], f"Phantom creations detected: {names}"
