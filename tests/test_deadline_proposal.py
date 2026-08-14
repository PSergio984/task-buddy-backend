"""Tests for the Phase 9 deadline proposal machinery (plan 09-02)."""

from datetime import datetime, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import DeadlineType, Task
from app.models.user import User
from app.planner.deadline import propose_deadline


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


async def create_task_via_api(
    client: AsyncClient, token: str, payload: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/tasks/", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201, f"Task creation failed: {response.text}"
    return cast(dict[str, Any], response.json())


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_propose_deadline_priority_scaling() -> None:
    high = propose_deadline(
        __import__("app.models.task", fromlist=["TaskPriority"]).TaskPriority.HIGH, now=NOW
    )
    medium = propose_deadline(
        __import__("app.models.task", fromlist=["TaskPriority"]).TaskPriority.MEDIUM, now=NOW
    )
    low = propose_deadline(
        __import__("app.models.task", fromlist=["TaskPriority"]).TaskPriority.LOW, now=NOW
    )
    assert (medium - NOW).days == 4
    assert (high - NOW).days == 2
    assert (low - NOW).days == 7


def test_propose_deadline_effort_bump() -> None:
    from app.models.task import TaskPriority

    assert (propose_deadline(TaskPriority.MEDIUM, 500, now=NOW) - NOW).days == 6
    assert (propose_deadline(TaskPriority.MEDIUM, 480, now=NOW) - NOW).days == 5
    assert (propose_deadline(TaskPriority.MEDIUM, 479, now=NOW) - NOW).days == 5


def test_propose_deadline_caps_at_14_days() -> None:
    from app.models.task import TaskPriority

    result = propose_deadline(TaskPriority.LOW, 10080, now=NOW)
    assert (result - NOW).days == 14


def test_propose_deadline_returns_timezone_aware() -> None:
    from app.models.task import TaskPriority

    result = propose_deadline(TaskPriority.HIGH, now=NOW)
    assert result.tzinfo is not None
    assert result.tzinfo == NOW.tzinfo


@pytest.mark.anyio
async def test_create_without_due_date_proposes_soft_never_persisted(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "dl_prop", "dl_prop@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    body = await create_task_via_api(async_client, token, {"title": "t1", "priority": "MEDIUM"})

    assert body["deadline_type"] == "soft"
    assert body["proposed_deadline"] is not None
    datetime.fromisoformat(body["proposed_deadline"].replace("Z", "+00:00"))

    row = (await db.execute(select(Task).where(Task.title == "t1"))).scalar_one()
    assert row.due_date is None
    assert row.deadline_type is None


@pytest.mark.anyio
async def test_create_with_due_date_marks_hard(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "dl_hard", "dl_hard@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    body = await create_task_via_api(
        async_client, token, {"title": "t2", "due_date": "2026-08-20T10:00:00Z"}
    )

    assert body["deadline_type"] == "hard"
    row = (await db.execute(select(Task).where(Task.title == "t2"))).scalar_one()
    assert row.deadline_type == DeadlineType.HARD
    assert row.due_date is not None


@pytest.mark.anyio
async def test_confirm_proposal_via_put_sets_soft_deadline(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "dl_confirm", "dl_confirm@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    body = await create_task_via_api(async_client, token, {"title": "t3"})
    response = await async_client.put(
        f"/api/v1/tasks/{body['id']}",
        json={"due_date": "2026-08-18T10:00:00Z", "deadline_type": "soft"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["deadline_type"] == "soft"

    row = (await db.execute(select(Task).where(Task.title == "t3"))).scalar_one()
    assert row.due_date is not None
    assert row.deadline_type == DeadlineType.SOFT


@pytest.mark.anyio
async def test_create_path_never_invokes_llm(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    mock_client = mocker.Mock()
    mock_client.chat.completions.create.side_effect = AssertionError("LLM called on create path")
    mocker.patch("app.knowledge.assistant._openai_client", return_value=mock_client)

    user = await register_user(db, async_client, "dl_nollm", "dl_nollm@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    body = await create_task_via_api(async_client, token, {"title": "t4"})
    assert body["id"] > 0
    mock_client.chat.completions.create.assert_not_called()
