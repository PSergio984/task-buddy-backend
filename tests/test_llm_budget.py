"""Tests for the per-user daily LLM token budget (audit #29)."""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.budget import BudgetExceededError, check_llm_budget, daily_llm_tokens_used
from app.models.knowledge import KnowledgeAnswer
from app.models.plan import PlanAnswer
from app.models.task import Task
from app.models.user import User


async def register_user(
    db: AsyncSession, client: AsyncClient, username: str, email: str
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/users/register",
        json={"username": username, "email": email, "password": "testpassword"},
    )
    assert response.status_code == 201, f"Registration failed: {response.text}"
    result = await db.execute(select(User).where(User.email == email))
    return {"id": result.scalar_one().id, "email": email, "password": "testpassword"}


async def confirm_user(db: AsyncSession, user: dict[str, Any]) -> None:
    from sqlalchemy import update

    await db.execute(update(User).where(User.email == user["email"]).values(confirmed=True))
    await db.commit()


async def login_user(client: AsyncClient, user: dict[str, Any]) -> str:
    response = await client.post(
        "/api/v1/users/token",
        data={"username": user["email"], "password": user["password"]},
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    return cast(str, response.json()["access_token"])


async def seed_ask_tokens(db: AsyncSession, user_id: int, total: int) -> None:
    """Insert one KnowledgeAnswer row carrying `total` tokens for today."""
    task = Task(title="budget task", completed=False, priority="MEDIUM", user_id=user_id)
    db.add(task)
    await db.flush()
    db.add(
        KnowledgeAnswer(
            user_id=user_id,
            task_id=task.id,
            answer="a",
            model="test",
            prompt_tokens=total,
            completion_tokens=0,
            total_tokens=total,
            cost_usd=0,
            response_time_ms=1,
            retrieved_chunks=[],
        )
    )
    await db.commit()


async def seed_plan_tokens(db: AsyncSession, user_id: int, total: int) -> None:
    db.add(
        PlanAnswer(
            user_id=user_id,
            answer="p",
            model="test",
            prompt_tokens=total,
            completion_tokens=0,
            total_tokens=total,
            cost_usd=0,
            response_time_ms=1,
            pool_size=0,
            available_minutes=0,
        )
    )
    await db.commit()


@pytest.mark.anyio
async def test_daily_usage_sums_ask_and_plan(db: AsyncSession, async_client: AsyncClient) -> None:
    user = await register_user(db, async_client, "budget_sum", "budget_sum@example.com")
    await seed_ask_tokens(db, user["id"], 300)
    await seed_plan_tokens(db, user["id"], 700)
    assert await daily_llm_tokens_used(db, user["id"]) == 1000


@pytest.mark.anyio
async def test_check_budget_raises_when_exhausted(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "budget_over", "budget_over@example.com")
    await seed_ask_tokens(db, user["id"], 300)
    await seed_plan_tokens(db, user["id"], 700)
    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 500)
    with pytest.raises(BudgetExceededError):
        await check_llm_budget(db, user["id"])


@pytest.mark.anyio
async def test_check_budget_passes_under_limit(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "budget_ok", "budget_ok@example.com")
    await seed_plan_tokens(db, user["id"], 400)
    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 1000)
    await check_llm_budget(db, user["id"])  # must not raise


@pytest.mark.anyio
async def test_check_budget_disabled_at_zero(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "budget_zero", "budget_zero@example.com")
    await seed_plan_tokens(db, user["id"], 9999)
    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 0)
    await check_llm_budget(db, user["id"])  # 0 disables the cap


@pytest.mark.anyio
async def test_plan_returns_429_when_budget_exhausted(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """An over-budget user gets 429 before any LLM call is made."""
    user = await register_user(db, async_client, "budget_429", "budget_429@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_plan_tokens(db, user["id"], 150)

    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 100)
    boom = mocker.patch(
        "app.knowledge.assistant._openai_client",
        side_effect=AssertionError("LLM called despite budget"),
    )

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 429
    assert "usage limit" in response.json()["detail"].lower()
    boom.assert_not_called()


@pytest.mark.anyio
async def test_ask_returns_429_when_budget_exhausted(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "budget_ask", "budget_ask@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "budget ask task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_plan_tokens(db, user["id"], 150)

    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 100)
    boom = mocker.patch(
        "app.knowledge.assistant._openai_client",
        side_effect=AssertionError("LLM called despite budget"),
    )

    task_id = task_resp.json()["id"]
    response = await async_client.post(
        f"/api/v1/tasks/{task_id}/knowledge/ask",
        json={"query": "what do I need"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 429
    boom.assert_not_called()
