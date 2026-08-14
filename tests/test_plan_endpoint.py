"""Tests for the Phase 9 plan endpoint + service (plan 09-04)."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.assistant import AssistantNotConfiguredError
from app.knowledge.history import create_history_knowledge
from app.models.plan import PlanAnswer
from app.models.task import Task, TaskPriority
from app.models.user import User
from app.planner.service import build_pool

WED = date = __import__("datetime").date(2026, 8, 19)

PLAN_JSON = {
    "buckets": [
        {
            "period": "tonight",
            "tasks": [{"task_id": 1, "reason": "urgent", "effort_minutes": 30}],
        },
        {
            "period": "tomorrow",
            "tasks": [{"task_id": 2, "reason": "due soon", "effort_minutes": 60}],
        },
    ]
}


def fake_chat_completion(content: str, prompt_tokens: int, completion_tokens: int) -> Any:
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


def patch_openai(mocker: Any, json_payload: dict[str, Any]) -> Any:
    """Patch the assistant client with a fake returning `json_payload`."""
    fake_response = fake_chat_completion(json.dumps(json_payload), 100, 20)
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)
    return fake_client


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


async def plan_row_count(db: AsyncSession) -> int:
    return (
        await db.execute(select(func.count()).select_from(PlanAnswer))
    ).scalar_one()


def captured_prompt(fake_client: Any) -> dict[str, Any]:
    """The user-message payload the fake client received."""
    messages = fake_client.chat.completions.create.call_args.kwargs["messages"]
    return json.loads(messages[-1]["content"])


@pytest.mark.anyio
async def test_plan_requires_auth_401(async_client: AsyncClient) -> None:
    response = await async_client.post("/api/v1/plan", json={})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_plan_pool_scoped_to_owner(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    owner = await register_user(db, async_client, "pl_owner", "pl_owner@example.com")
    await confirm_user(db, owner)
    owner_token = await login_user(async_client, owner)
    other = await register_user(db, async_client, "pl_other", "pl_other@example.com")
    await confirm_user(db, other)
    other_token = await login_user(async_client, other)

    await create_task_via_api(async_client, owner_token, {"title": "Owner task A"})
    await create_task_via_api(async_client, owner_token, {"title": "Owner task B"})
    await create_task_via_api(async_client, other_token, {"title": "Other task"})

    fake_client = patch_openai(mocker, PLAN_JSON)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pool_size"] == 2
    payload = captured_prompt(fake_client)
    titles = [t["title"] for t in payload["tasks"]]
    assert "Owner task A" in titles and "Owner task B" in titles
    assert "Other task" not in titles


@pytest.mark.anyio
async def test_plan_zero_open_tasks_short_circuits(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_zero", "pl_zero@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    fake_client = patch_openai(mocker, PLAN_JSON)

    response = await async_client.post(
        "/api/v1/plan",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["buckets"] == []
    assert body["reason"] == "no open tasks"
    assert body["model"] == "rule"
    fake_client.chat.completions.create.assert_not_called()


@pytest.mark.anyio
async def test_plan_zero_available_minutes_short_circuits(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_notime", "pl_notime@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await create_task_via_api(async_client, token, {"title": "Task"})

    fake_client = patch_openai(mocker, PLAN_JSON)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["buckets"] == []
    assert body["reason"] == "no free time today"
    assert body["model"] == "rule"
    fake_client.chat.completions.create.assert_not_called()


@pytest.mark.anyio
async def test_plan_explicit_available_minutes_wins_over_connector(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_expl", "pl_expl@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await create_task_via_api(async_client, token, {"title": "Task"})

    fake_client = patch_openai(mocker, PLAN_JSON)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 90},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = captured_prompt(fake_client)
    assert payload["available_minutes"] == 90


@pytest.mark.anyio
async def test_plan_connector_used_when_available_minutes_omitted(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_conn", "pl_conn@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await create_task_via_api(async_client, token, {"title": "Task"})

    mocker.patch(
        "app.planner.service.date",
        SimpleNamespace(today=lambda: WED),
    )
    fake_client = patch_openai(mocker, PLAN_JSON)

    response = await async_client.post(
        "/api/v1/plan",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = captured_prompt(fake_client)
    assert payload["available_minutes"] == 150  # demo dataset


@pytest.mark.anyio
async def test_plan_config_default_when_connector_disabled(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_cfg", "pl_cfg@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await create_task_via_api(async_client, token, {"title": "Task"})

    mocker.patch("app.api.routers.plan.SYNTHETIC_CALENDAR_ENABLED", False)
    fake_client = patch_openai(mocker, PLAN_JSON)

    response = await async_client.post(
        "/api/v1/plan",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = captured_prompt(fake_client)
    assert payload["available_minutes"] == 120  # PLANNER_DEFAULT_AVAILABLE_MINUTES


@pytest.mark.anyio
async def test_plan_limit_caps_returned_tasks(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_limit", "pl_limit@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    tasks = []
    for i in range(3):
        tasks.append(await create_task_via_api(async_client, token, {"title": f"Task {i}"}))

    payload = {
        "buckets": [
            {
                "period": "tonight",
                "tasks": [
                    {"task_id": tasks[0]["id"], "reason": "a", "effort_minutes": 10},
                    {"task_id": tasks[1]["id"], "reason": "b", "effort_minutes": 10},
                ],
            },
            {
                "period": "tomorrow",
                "tasks": [
                    {"task_id": tasks[2]["id"], "reason": "c", "effort_minutes": 10}
                ],
            },
        ]
    }
    patch_openai(mocker, payload)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120, "limit": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    total = sum(len(b["tasks"]) for b in body["buckets"])
    assert total == 2


@pytest.mark.anyio
async def test_plan_happy_path_returns_buckets_and_metrics(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_happy", "pl_happy@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    t1 = await create_task_via_api(async_client, token, {"title": "T1"})
    t2 = await create_task_via_api(async_client, token, {"title": "T2"})

    payload = {
        "buckets": [
            {
                "period": "tonight",
                "tasks": [{"task_id": t1["id"], "reason": "r1", "effort_minutes": 30}],
            },
            {
                "period": "tomorrow",
                "tasks": [{"task_id": t2["id"], "reason": "r2", "effort_minutes": 60}],
            },
        ]
    }
    patch_openai(mocker, payload)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["buckets"]) == 2
    assert body["buckets"][0]["period"] == "tonight"
    assert body["buckets"][0]["tasks"][0]["task_id"] == t1["id"]
    assert body["plan_id"] is not None
    assert body["model"] == "gpt-4o-mini"
    assert body["prompt_tokens"] > 0
    assert body["cost_usd"] > 0
    assert body["response_time_ms"] >= 0


@pytest.mark.anyio
async def test_plan_persists_instrumented_row(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_persist", "pl_persist@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await create_task_via_api(async_client, token, {"title": "T"})

    patch_openai(mocker, PLAN_JSON)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    assert await plan_row_count(db) == 1
    row = (await db.execute(select(PlanAnswer))).scalar_one()
    assert row.model == "gpt-4o-mini"
    assert row.pool_size == 1
    assert row.available_minutes == 120
    json.loads(row.answer)  # parses as JSON


@pytest.mark.anyio
async def test_plan_whitelist_drops_unknown_task_ids(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_white", "pl_white@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task = await create_task_via_api(async_client, token, {"title": "T"})

    payload = {
        "buckets": [
            {
                "period": "tonight",
                "tasks": [
                    {"task_id": task["id"], "reason": "ok", "effort_minutes": 10},
                    {"task_id": 999999, "reason": "fake", "effort_minutes": 10},
                ],
            }
        ]
    }
    patch_openai(mocker, payload)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    ids = [t["task_id"] for b in body["buckets"] for t in b["tasks"]]
    assert ids == [task["id"]]


@pytest.mark.anyio
async def test_plan_collapses_duplicate_task_ids(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_dup", "pl_dup@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task = await create_task_via_api(async_client, token, {"title": "T"})

    payload = {
        "buckets": [
            {
                "period": "tonight",
                "tasks": [{"task_id": task["id"], "reason": "first", "effort_minutes": 10}],
            },
            {
                "period": "tomorrow",
                "tasks": [{"task_id": task["id"], "reason": "second", "effort_minutes": 10}],
            },
        ]
    }
    patch_openai(mocker, payload)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    ids = [t["task_id"] for b in body["buckets"] for t in b["tasks"]]
    assert ids == [task["id"]]


@pytest.mark.anyio
async def test_plan_parse_failure_degrades_to_empty_buckets(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_parse", "pl_parse@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await create_task_via_api(async_client, token, {"title": "T"})

    patch_openai(mocker, {"garbage": True})

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["buckets"] == []
    assert body["reason"] == "plan could not be generated"
    assert await plan_row_count(db) == 1


@pytest.mark.anyio
async def test_plan_503_when_assistant_not_configured(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_nokey", "pl_nokey@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await create_task_via_api(async_client, token, {"title": "T"})

    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.side_effect = AssistantNotConfiguredError("no key")
    mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AI assistant not configured"


@pytest.mark.anyio
async def test_plan_503_when_provider_unavailable(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    import openai

    user = await register_user(db, async_client, "pl_prov", "pl_prov@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await create_task_via_api(async_client, token, {"title": "T"})

    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.side_effect = openai.APIError(
        "provider boom", request=None, body=None
    )
    mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AI assistant unavailable"


@pytest.mark.anyio
async def test_plan_short_circuit_persists_zeroed_row(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_zrow", "pl_zrow@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    patch_openai(mocker, PLAN_JSON)

    response = await async_client.post(
        "/api/v1/plan",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    assert await plan_row_count(db) == 1
    row = (await db.execute(select(PlanAnswer))).scalar_one()
    assert row.model == "rule"
    assert row.prompt_tokens == 0
    assert row.cost_usd == 0


@pytest.mark.anyio
async def test_plan_user_estimate_wins_over_memory_hint(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_est", "pl_est@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    # Seed a history row with duration via the Phase 8 helper.
    hist_task = Task(
        title="Write report",
        description="Full report",
        completed=True,
        created_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, 11, 30, tzinfo=timezone.utc),
        user_id=user["id"],
    )
    db.add(hist_task)
    await db.flush()
    await create_history_knowledge(db, hist_task)
    # Release the fixture session's write transaction (flush-not-commit) so
    # the API session can write without hitting the SQLite single-writer lock.
    await db.commit()

    await create_task_via_api(
        async_client,
        token,
        {"title": "Write report", "description": "Full report", "estimated_effort_minutes": 45},
    )

    fake_client = patch_openai(mocker, PLAN_JSON)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = captured_prompt(fake_client)
    row = payload["tasks"][0]
    assert row["estimated_effort_minutes"] == 45
    assert row["memory_hint_minutes"] is None


@pytest.mark.anyio
async def test_plan_memory_hint_used_when_estimate_missing(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    user = await register_user(db, async_client, "pl_hint", "pl_hint@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    hist_task = Task(
        title="Write report",
        description="Full report",
        completed=True,
        created_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, 11, 30, tzinfo=timezone.utc),
        user_id=user["id"],
    )
    db.add(hist_task)
    await db.flush()
    await create_history_knowledge(db, hist_task)
    # Release the fixture session's write transaction (flush-not-commit) so
    # the API session can write without hitting the SQLite single-writer lock.
    await db.commit()

    await create_task_via_api(
        async_client, token, {"title": "Write report", "description": "Full report"}
    )

    fake_client = patch_openai(mocker, PLAN_JSON)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = captured_prompt(fake_client)
    row = payload["tasks"][0]
    assert row["estimated_effort_minutes"] is None
    assert row["memory_hint_minutes"] == 90.0


@pytest.mark.anyio
async def test_pool_builder_urgency_ordering_and_cap(
    db: AsyncSession, mocker: Any
) -> None:
    user = User(username="pl_pool", email="pl_pool@example.com", password="x")
    db.add(user)
    await db.flush()

    tomorrow = datetime(2026, 1, 10, tzinfo=timezone.utc)
    next_week = datetime(2026, 1, 15, tzinfo=timezone.utc)

    no_due = Task(title="no due", priority=TaskPriority.HIGH, user_id=user.id)
    due_tomorrow = Task(
        title="due tomorrow",
        priority=TaskPriority.LOW,
        due_date=tomorrow,
        user_id=user.id,
    )
    due_next = Task(
        title="due next",
        priority=TaskPriority.MEDIUM,
        due_date=next_week,
        user_id=user.id,
    )
    db.add_all([no_due, due_tomorrow, due_next])
    await db.flush()

    pool = await build_pool(db, user.id)
    titles = [t.title for t in pool]
    assert titles[0] == "due tomorrow"  # earliest due date first
    assert titles[1] == "due next"
    assert titles[2] == "no due"  # NULL due_date LAST (nulls_last)

    # Priority tiebreak among equal due_dates.
    eq1 = Task(
        title="high eq",
        priority=TaskPriority.HIGH,
        due_date=tomorrow,
        user_id=user.id,
    )
    eq2 = Task(
        title="med eq",
        priority=TaskPriority.MEDIUM,
        due_date=tomorrow,
        user_id=user.id,
    )
    db.add_all([eq1, eq2])
    await db.flush()

    pool2 = await build_pool(db, user.id)
    high_idx = next(i for i, t in enumerate(pool2) if t.title == "high eq")
    med_idx = next(i for i, t in enumerate(pool2) if t.title == "med eq")
    assert high_idx < med_idx

    # Pool cap at 50.
    for i in range(55):
        db.add(Task(title=f"bulk {i}", user_id=user.id))
    await db.flush()
    pool3 = await build_pool(db, user.id)
    assert len(pool3) == 50
