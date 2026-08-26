"""Budget reservation race tests (RELI-01 / RELI-03 race target 1).

These tests exercise await-point interleaving deterministically: aiosqlite
funnels all writes through a single connection inside one event loop, so the
gather below proves the compare-and-set logic — which is dialect-independent
— rather than kernel-level parallelism. The Postgres CI migration job covers
the real-database DDL leg.
"""

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import LlmUsageReservation
from app.models.task import Task
from app.models.user import User
from tests.conftest import TestSessionLocal

PLAN_CONTENT = json.dumps(
    {
        "buckets": [
            {
                "period": "tonight",
                "tasks": [{"task_id": 999999, "reason": "race", "effort_minutes": 30}],
            }
        ]
    }
)


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


def patch_provider_success(mocker: Any, total_tokens: int) -> Any:
    """Mock the provider seam so /plan succeeds with usage.total_tokens set.

    Shaping usage.total_tokens == the reservation estimate makes reconcile
    net zero, which is what lets the post-commit counter assertion hold at
    exactly successes * estimate.
    """
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=PLAN_CONTENT))],
        usage=SimpleNamespace(
            prompt_tokens=total_tokens - 20,
            completion_tokens=20,
            total_tokens=total_tokens,
        ),
    )
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)
    return fake_client


@pytest.mark.anyio
async def test_reservation_atomic_under_gather(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """N concurrent reserves, cap 1000, estimate 300 → exactly floor(1000/300)=3 win.

    Pass condition: successes * estimate <= cap < (successes + 1) * estimate,
    and the committed counter equals successes * estimate exactly — overshoot
    is impossible regardless of interleaving because every increment is one
    conditional UPDATE whose predicate re-reads the committed balance.
    """
    user = await register_user(db, async_client, "resv_race", "resv_race@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    # At least one open task so every request takes the real LLM path (no
    # planner rule short-circuit) and consumes its mocked 300-token usage.
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "race task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201

    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 1000)
    mocker.patch("app.api.routers.plan.LLM_PLAN_RESERVE_TOKENS", 300)
    patch_provider_success(mocker, total_tokens=300)

    responses = await asyncio.gather(
        *[
            async_client.post(
                "/api/v1/plan",
                json={"available_minutes": 120},
                headers={"Authorization": f"Bearer {token}"},
            )
            for _ in range(20)
        ]
    )

    successful = [r for r in responses if r.status_code == 200]
    throttled = [r for r in responses if r.status_code == 429]
    assert len(successful) == 3, (
        f"expected exactly floor(1000/300)=3 successes, got {len(successful)}: "
        f"{[r.status_code for r in responses]}"
    )
    assert len(throttled) == 17
    assert all("usage limit" in r.json()["detail"].lower() for r in throttled)

    # Fresh session — the db fixture rolls back and its transaction began
    # before these commits, so it must not be used for post-commit reads.
    async with TestSessionLocal() as fresh:
        row = (
            await fresh.execute(
                select(LlmUsageReservation).where(LlmUsageReservation.user_id == user["id"])
            )
        ).scalar_one()
        assert row.reserved_tokens == 900  # successes * estimate — no overshoot


@pytest.mark.anyio
async def test_reservation_row_lazily_created_first_of_day(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """The first reserve of a UTC day creates the counter row; none exist before."""
    user = await register_user(db, async_client, "resv_lazy", "resv_lazy@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await async_client.post(
        "/api/v1/tasks/",
        json={"title": "lazy task"},
        headers={"Authorization": f"Bearer {token}"},
    )

    async with TestSessionLocal() as fresh:
        count_before = len(
            (await fresh.execute(select(LlmUsageReservation))).scalars().all()
        )
    assert count_before == 0  # tbl_llm_usage_reservations starts empty

    mocker.patch("app.api.routers.plan.LLM_PLAN_RESERVE_TOKENS", 300)
    patch_provider_success(mocker, total_tokens=300)

    resp = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    async with TestSessionLocal() as fresh:
        row = (
            await fresh.execute(
                select(LlmUsageReservation).where(LlmUsageReservation.user_id == user["id"])
            )
        ).scalar_one()
        assert row.reserved_tokens == 300  # reserve est then reconcile(actual==est) nets zero


@pytest.mark.anyio
async def test_plan_succeeds_with_mocked_provider_under_default_budget(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """Sanity: normal budget + mocked provider → 200 through the reservation gate."""
    user = await register_user(db, async_client, "resv_ok", "resv_ok@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task = Task(title="plan task", completed=False, priority="MEDIUM", user_id=user["id"])
    db.add(task)
    await db.commit()

    patch_provider_success(mocker, total_tokens=5000)  # under the 8000 default estimate

    resp = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
