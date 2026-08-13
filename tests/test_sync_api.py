"""Integration tests for POST /api/v1/sync (LWW round trip, delta, auth)."""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.user import User

UTC = timezone.utc


def _ts(hours_ahead: float) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours_ahead)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_task(client: AsyncClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/api/v1/tasks/", json=body, headers=_auth(token))
    assert response.status_code == 201, f"Task creation failed: {response.text}"
    return cast(dict[str, Any], response.json())


async def register_user(
    db: AsyncSession, client: AsyncClient, username: str, email: str
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/users/register",
        json={"username": username, "email": email, "password": "testpassword"},
    )
    assert response.status_code == 201, f"Registration failed: {response.text}"
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one()
    return {"id": user.id, "username": username, "email": email, "password": "testpassword"}


async def confirm_user(db: AsyncSession, user: dict[str, Any]) -> None:
    stmt = update(User).where(User.email == user["email"]).values(confirmed=True)
    await db.execute(stmt)
    await db.commit()


async def login_user(client: AsyncClient, user: dict[str, Any]) -> str:
    response = await client.post(
        "/api/v1/users/token",
        data={"username": user["email"], "password": user["password"]},
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    token = cast(str, response.json().get("access_token"))
    assert token, "Login response missing access_token"
    return token


async def post_sync(client: AsyncClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/api/v1/sync", json=body, headers=_auth(token))
    assert response.status_code == 200, f"Sync failed: {response.text}"
    return cast(dict[str, Any], response.json())


async def test_sync_requires_auth(async_client: AsyncClient) -> None:
    response = await async_client.post("/api/v1/sync", json={"changes": []})
    assert response.status_code == 401


async def test_sync_round_trip_applies_changes(
    async_client: AsyncClient, logged_in_token: str
) -> None:
    task = await create_task(async_client, logged_in_token, {"title": "Original"})
    client_ts = _ts(1)

    result = await post_sync(
        async_client,
        logged_in_token,
        {
            "changes": [
                {
                    "entity": "task",
                    "id": task["id"],
                    "op": "update",
                    "payload": {"title": "Synced Title"},
                    "client_updated_at": client_ts.isoformat(),
                }
            ]
        },
    )

    assert len(result["applied"]) == 1
    assert result["applied"][0]["id"] == task["id"]
    assert result["conflicts"] == []
    assert result["not_found"] == []

    response = await async_client.get(f"/api/v1/tasks/{task['id']}", headers=_auth(logged_in_token))
    assert response.status_code == 200
    assert response.json()["title"] == "Synced Title"
    # Strict LWW: the row takes the client's timestamp, not the server's now.
    server_ts = datetime.fromisoformat(response.json()["updated_at"])
    # SQLite's DateTime storage drops the tz tag (Postgres round-trips it);
    # the wall-clock value must still equal the client timestamp.
    assert server_ts.replace(tzinfo=UTC) == client_ts


async def test_sync_stale_change_conflicts(async_client: AsyncClient, logged_in_token: str) -> None:
    task = await create_task(async_client, logged_in_token, {"title": "Keep Me"})

    result = await post_sync(
        async_client,
        logged_in_token,
        {
            "changes": [
                {
                    "entity": "task",
                    "id": task["id"],
                    "op": "update",
                    "payload": {"title": "Stale"},
                    "client_updated_at": _ts(-1).isoformat(),
                }
            ]
        },
    )

    assert result["applied"] == []
    assert len(result["conflicts"]) == 1
    conflict = result["conflicts"][0]
    assert conflict["id"] == task["id"]
    # Server state returned so the client converges — title is untouched.
    assert conflict["server_state"]["title"] == "Keep Me"

    response = await async_client.get(f"/api/v1/tasks/{task['id']}", headers=_auth(logged_in_token))
    assert response.json()["title"] == "Keep Me"


async def test_sync_unknown_row_not_found(async_client: AsyncClient, logged_in_token: str) -> None:
    result = await post_sync(
        async_client,
        logged_in_token,
        {
            "changes": [
                {
                    "entity": "task",
                    "id": 999999,
                    "op": "update",
                    "payload": {"title": "Ghost"},
                    "client_updated_at": _ts(1).isoformat(),
                }
            ]
        },
    )
    assert result["applied"] == []
    assert len(result["not_found"]) == 1
    assert result["not_found"][0]["id"] == 999999


async def test_sync_delta_returns_rows_since(
    async_client: AsyncClient, logged_in_token: str
) -> None:
    before = _ts(-2)
    await create_task(async_client, logged_in_token, {"title": "Old Task"})

    result = await post_sync(
        async_client, logged_in_token, {"since": before.isoformat(), "changes": []}
    )
    assert len(result["delta"]["tasks"]) == 1
    assert result["delta"]["tasks"][0]["title"] == "Old Task"

    # New high-water mark: a second sync after now() returns nothing new.
    after = _ts(2)
    result2 = await post_sync(
        async_client, logged_in_token, {"since": after.isoformat(), "changes": []}
    )
    assert result2["delta"]["tasks"] == []


async def test_sync_other_user_isolated(
    db: AsyncSession, async_client: AsyncClient, confirmed_user: dict[str, Any]
) -> None:
    user2 = await register_user(db, async_client, "syncuser2", "syncuser2@example.com")
    await confirm_user(db, user2)
    token2 = await login_user(async_client, user2)
    token1 = await login_user(async_client, confirmed_user)

    task = await create_task(async_client, token1, {"title": "User 1 Private"})

    # User 2 pushes a change to User 1's task -> not_found, no mutation.
    result = await post_sync(
        async_client,
        token2,
        {
            "changes": [
                {
                    "entity": "task",
                    "id": task["id"],
                    "op": "update",
                    "payload": {"title": "Hijacked"},
                    "client_updated_at": _ts(1).isoformat(),
                }
            ]
        },
    )
    assert result["applied"] == []
    assert len(result["not_found"]) == 1

    # User 2's delta never contains User 1's rows.
    result2 = await post_sync(async_client, token2, {"since": _ts(-2).isoformat(), "changes": []})
    assert result2["delta"]["tasks"] == []


async def test_sync_delete_applied(async_client: AsyncClient, logged_in_token: str) -> None:
    task = await create_task(async_client, logged_in_token, {"title": "Doomed"})

    result = await post_sync(
        async_client,
        logged_in_token,
        {
            "changes": [
                {
                    "entity": "task",
                    "id": task["id"],
                    "op": "delete",
                    "payload": {},
                    "client_updated_at": _ts(1).isoformat(),
                }
            ]
        },
    )
    assert len(result["applied"]) == 1
    assert result["applied"][0]["op"] == "delete"

    response = await async_client.get(f"/api/v1/tasks/{task['id']}", headers=_auth(logged_in_token))
    assert response.status_code == 404


async def test_sync_validation_bad_entity(async_client: AsyncClient, logged_in_token: str) -> None:
    response = await async_client.post(
        "/api/v1/sync",
        json={
            "changes": [
                {
                    "entity": "banana",
                    "id": 1,
                    "op": "update",
                    "payload": {},
                    "client_updated_at": _ts(1).isoformat(),
                }
            ]
        },
        headers=_auth(logged_in_token),
    )
    assert response.status_code == 422


async def test_sync_subtask_update_applied(async_client: AsyncClient, logged_in_token: str) -> None:
    task = await create_task(async_client, logged_in_token, {"title": "Parent"})
    subtask_response = await async_client.post(
        "/api/v1/tasks/subtask",
        json={"title": "Child", "task_id": task["id"]},
        headers=_auth(logged_in_token),
    )
    assert subtask_response.status_code == 201
    subtask = subtask_response.json()

    result = await post_sync(
        async_client,
        logged_in_token,
        {
            "changes": [
                {
                    "entity": "subtask",
                    "id": subtask["id"],
                    "op": "update",
                    "payload": {"title": "Synced Child", "position": 5},
                    "client_updated_at": _ts(1).isoformat(),
                }
            ]
        },
    )
    assert len(result["applied"]) == 1
    assert result["applied"][0]["entity"] == "subtask"

    response = await async_client.get(f"/api/v1/tasks/{task['id']}", headers=_auth(logged_in_token))
    body = response.json()
    synced = next(s for s in body["subtasks"] if s["id"] == subtask["id"])
    assert synced["title"] == "Synced Child"
    assert synced["position"] == 5


async def test_sync_project_update_applied(async_client: AsyncClient, logged_in_token: str) -> None:
    response = await async_client.post(
        "/api/v1/projects/",
        json={"name": "Original Project"},
        headers=_auth(logged_in_token),
    )
    assert response.status_code == 201
    project = response.json()

    result = await post_sync(
        async_client,
        logged_in_token,
        {
            "changes": [
                {
                    "entity": "project",
                    "id": project["id"],
                    "op": "update",
                    "payload": {"name": "Synced Project", "color": "#ff0000"},
                    "client_updated_at": _ts(1).isoformat(),
                }
            ]
        },
    )
    assert len(result["applied"]) == 1
    assert result["applied"][0]["entity"] == "project"

    list_response = await async_client.get("/api/v1/projects/", headers=_auth(logged_in_token))
    synced = next(p for p in list_response.json() if p["id"] == project["id"])
    assert synced["name"] == "Synced Project"
    assert synced["color"] == "#ff0000"


async def test_sync_429_carries_retry_after(
    authenticated_async_client: AsyncClient, mocker: Any
) -> None:
    """The global RateLimitExceeded handler (which covers /api/v1/sync)
    emits Retry-After — the server-side SYNC-03 hint."""
    limiter_enabled = app.state.limiter.enabled
    app.state.limiter.enabled = True
    app.state.limiter.reset()
    try:
        mocker.patch("slowapi.util.get_remote_address", return_value="9.9.9.9")
        for _ in range(10):
            response = await authenticated_async_client.post(
                "/api/v1/projects/", json={"name": f"RL {datetime.now(UTC)}"}
            )
            assert response.status_code != 429
        response = await authenticated_async_client.post(
            "/api/v1/projects/", json={"name": "Rate Limited"}
        )
        assert response.status_code == 429
        assert response.headers.get("Retry-After") is not None
    finally:
        app.state.limiter.reset()
        app.state.limiter.enabled = limiter_enabled
