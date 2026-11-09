"""Tests for the per-user daily LLM token budget (audit #29; ADR 0002)."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import openai
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    LLM_ASK_RESERVE_TOKENS,
    LLM_BREAKDOWN_RESERVE_TOKENS,
    LLM_PLAN_RESERVE_TOKENS,
    LLM_VOICE_RESERVE_TOKENS,
)
from app.knowledge.assistant import AssistantNotConfiguredError, KnowledgeAssistant
from app.knowledge.budget import BudgetExceededError, daily_llm_tokens_used, reserve_llm_budget
from app.models.breakdown import BreakdownAnswer
from app.models.budget import LlmUsageReservation
from app.models.knowledge import KnowledgeAnswer
from app.models.plan import PlanAnswer
from app.models.task import Task
from app.models.user import User
from tests.conftest import TestSessionLocal


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


async def seed_breakdown_tokens(db: AsyncSession, user_id: int, total: int) -> None:
    db.add(
        BreakdownAnswer(
            user_id=user_id,
            answer="b",
            model="test",
            prompt_tokens=total,
            completion_tokens=0,
            total_tokens=total,
            cost_usd=0,
            response_time_ms=1,
            input_chars=1,
        )
    )
    await db.commit()


@pytest.mark.anyio
async def test_daily_usage_includes_breakdown_tokens(
    db: AsyncSession, async_client: AsyncClient
) -> None:
    user = await register_user(db, async_client, "budget_bd", "budget_bd@example.com")
    await seed_breakdown_tokens(db, user["id"], 250)
    assert await daily_llm_tokens_used(db, user["id"]) == 250


@pytest.mark.anyio
async def test_daily_usage_sums_ask_and_plan(db: AsyncSession, async_client: AsyncClient) -> None:
    user = await register_user(db, async_client, "budget_sum", "budget_sum@example.com")
    await seed_ask_tokens(db, user["id"], 300)
    await seed_plan_tokens(db, user["id"], 700)
    assert await daily_llm_tokens_used(db, user["id"]) == 1000


@pytest.mark.anyio
async def test_reserve_raises_when_counter_would_exceed_cap(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """Reservation contract (ADR 0002): a reserve that would push the counter
    past the cap raises and leaves the committed balance untouched."""
    user = await register_user(db, async_client, "budget_over", "budget_over@example.com")
    await seed_reservation(db, user["id"], 400)
    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 500)
    with pytest.raises(BudgetExceededError):
        await reserve_llm_budget(db, user["id"], 200)
    # CAS proof: zero rows updated → the committed counter did not move.
    await db.rollback()
    assert await counter_value(user["id"]) == 400


@pytest.mark.anyio
async def test_reserve_passes_under_limit_and_increments_counter(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A reserve under the cap succeeds and commits its estimate."""
    user = await register_user(db, async_client, "budget_ok", "budget_ok@example.com")
    await seed_reservation(db, user["id"], 300)
    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 1000)
    await reserve_llm_budget(db, user["id"], 600)  # must not raise
    assert await counter_value(user["id"]) == 900


@pytest.mark.anyio
async def test_reserve_disabled_at_zero_cap(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """Cap <= 0 disables the gate entirely, even with prior spend reserved."""
    user = await register_user(db, async_client, "budget_zero", "budget_zero@example.com")
    await seed_reservation(db, user["id"], 9999)
    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 0)
    await reserve_llm_budget(db, user["id"], 5000)  # 0 disables the cap
    assert await counter_value(user["id"]) == 9999  # counter untouched


@pytest.mark.anyio
async def test_plan_returns_429_when_budget_exhausted(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A user whose reserved counter would exceed the cap gets 429 before any
    LLM call is made (ADR 0002 reservation contract)."""
    user = await register_user(db, async_client, "budget_429", "budget_429@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    # 900 of a 1000 cap already reserved today; a further 300-token estimate
    # cannot fit → the conditional UPDATE hits zero rows.
    await seed_reservation(db, user["id"], 900)

    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 1000)
    mocker.patch("app.api.routers.plan.LLM_PLAN_RESERVE_TOKENS", 300)
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
    # 900 of a 1000 cap already reserved today; a further 600-token estimate
    # cannot fit → 429 before the assistant runs (reservation contract).
    await seed_reservation(db, user["id"], 900)

    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 1000)
    mocker.patch("app.api.routers.knowledge.LLM_ASK_RESERVE_TOKENS", 600)
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


# ---------------------------------------------------------------------------
# Reservation seam (ADR 0002): refund-on-provider-error at every endpoint.
# Each test seeds a nonzero base balance so the assertion proves the refund
# actually fired (0 -> 0 would also pass if reserve never happened).
# ---------------------------------------------------------------------------

_BASE_BALANCE = 500


async def seed_reservation(db: AsyncSession, user_id: int, tokens: int) -> None:
    db.add(
        LlmUsageReservation(
            user_id=user_id, day=datetime.now(timezone.utc).date(), reserved_tokens=tokens
        )
    )
    await db.commit()


async def counter_value(user_id: int) -> int:
    """Fresh-session read of today's reservation counter (never the db fixture)."""
    async with TestSessionLocal() as fresh:
        row = (
            await fresh.execute(
                select(LlmUsageReservation).where(LlmUsageReservation.user_id == user_id)
            )
        ).scalar_one()
        return int(row.reserved_tokens)


@pytest.mark.anyio
async def test_plan_provider_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "refnd_pl", "refnd_pl@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    # Seed an open task: with an empty pool the planner short-circuits to a
    # rule-based 200 without ever calling the provider (D-08), so the refund
    # path would never be exercised.
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "plan refund task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._openai_client",
        side_effect=openai.APIError("provider boom", request=None, body=None),
    )

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_plan_not_configured_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "refnd_pln", "refnd_pln@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    # Open task required so the planner reaches the LLM call instead of the
    # D-08 short-circuit (see test_plan_provider_error_refunds_reservation).
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "plan not-configured task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._openai_client",
        side_effect=AssistantNotConfiguredError("no key"),
    )

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_breakdown_provider_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "refnd_bd", "refnd_bd@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=openai.APIError("provider boom", request=None, body=None),
    )

    response = await async_client.post(
        "/api/v1/breakdown",
        json={"text": "set up ci and deploy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_breakdown_not_configured_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "refnd_bdn", "refnd_bdn@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=AssistantNotConfiguredError("no key"),
    )

    response = await async_client.post(
        "/api/v1/breakdown",
        json={"text": "set up ci and deploy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_voice_stt_provider_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "refnd_vc", "refnd_vc@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    stt_client = mocker.MagicMock()
    stt_client.audio.transcriptions.create.side_effect = openai.APIError(
        "stt boom", request=None, body=None
    )
    mocker.patch("app.knowledge.voice._stt_client", return_value=stt_client)

    response = await async_client.post(
        "/api/v1/voice/plan",
        files={"audio": ("clip.webm", b"fake-audio-bytes", "audio/webm")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_voice_stt_not_configured_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "refnd_vcn", "refnd_vcn@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    stt_client = mocker.MagicMock()
    stt_client.audio.transcriptions.create.side_effect = AssistantNotConfiguredError("no groq key")
    mocker.patch("app.knowledge.voice._stt_client", return_value=stt_client)

    response = await async_client.post(
        "/api/v1/voice/plan",
        files={"audio": ("clip.webm", b"fake-audio-bytes", "audio/webm")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_ask_provider_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "refnd_ak", "refnd_ak@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "refund ask task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._openai_client",
        side_effect=openai.APIError("provider boom", request=None, body=None),
    )

    response = await async_client.post(
        f"/api/v1/tasks/{task_resp.json()['id']}/knowledge/ask",
        json={"query": "what do I need"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_ask_not_configured_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user = await register_user(db, async_client, "refnd_akn", "refnd_akn@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "refund ask task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._openai_client",
        side_effect=AssistantNotConfiguredError("no key"),
    )

    response = await async_client.post(
        f"/api/v1/tasks/{task_resp.json()['id']}/knowledge/ask",
        json={"query": "what do I need"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_ask_foreign_task_404_performs_no_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """Zero-spend-on-404: the ownership check runs before the reservation."""
    owner = await register_user(db, async_client, "own_task", "own_task@example.com")
    await confirm_user(db, owner)
    owner_token = await login_user(async_client, owner)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "owner only"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert task_resp.status_code == 201

    other = await register_user(db, async_client, "other_ask", "other_ask@example.com")
    await confirm_user(db, other)
    other_token = await login_user(async_client, other)
    boom = mocker.patch(
        "app.knowledge.assistant._openai_client",
        side_effect=AssertionError("LLM called on foreign task"),
    )

    response = await async_client.post(
        f"/api/v1/tasks/{task_resp.json()['id']}/knowledge/ask",
        json={"query": "sneaky"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert response.status_code == 404
    boom.assert_not_called()

    # No reservation row was created for the requester at all.
    async with TestSessionLocal() as fresh:
        rows = (
            (
                await fresh.execute(
                    select(LlmUsageReservation).where(LlmUsageReservation.user_id == other["id"])
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


# ---------------------------------------------------------------------------
# Reservation leak + missing-usage regressions (issue #95): the bug class
# fixed in the import endpoint applied to every sibling router — a failure
# inside the reserved window must refund (rolling back first when the session
# is poisoned), and a provider that omits usage must settle at the reserved
# amount rather than refund to zero.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_breakdown_generic_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A non-provider failure after the reserve still refunds — otherwise the
    prepaid tokens leak until UTC rollover and phantom 429s follow."""
    user = await register_user(db, async_client, "leak_bd", "leak_bd@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=RuntimeError("unexpected boom"),
    )
    with pytest.raises(RuntimeError):
        await async_client.post(
            "/api/v1/breakdown",
            json={"text": "set up ci and deploy"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_breakdown_pre_call_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A failure inside the reserved window before the provider call — here
    the memory-hints lookup — still refunds; the except-clause rollback
    recovers the poisoned session so the refund itself can run."""
    user = await register_user(db, async_client, "leak_bdh", "leak_bdh@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.api.routers.breakdown.fetch_memory_hints",
        side_effect=RuntimeError("db gone"),
    )
    # Class-level spy (same rationale as the import test): the request's
    # session isn't the db fixture's, and SQLite can't poison a transaction —
    # pin that the handler attempts rollback before refunding.
    rollback_spy = mocker.spy(AsyncSession, "rollback")
    with pytest.raises(RuntimeError):
        await async_client.post(
            "/api/v1/breakdown",
            json={"text": "set up ci and deploy"},
            headers={"Authorization": f"Bearer {token}"},
        )
    rollback_spy.assert_awaited()
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_breakdown_missing_usage_keeps_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A provider that omits ``usage`` reconciles at the reserved amount —
    conservative, the call must never become free under the daily cap."""
    user = await register_user(db, async_client, "leak_bdu", "leak_bdu@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    response_mock = mocker.Mock()
    response_mock.choices = [mocker.Mock()]
    response_mock.choices[0].message.content = json.dumps(
        {"tasks": [{"title": "T", "subtasks": []}]}
    )
    response_mock.usage = None
    mocker.patch("app.knowledge.assistant._call_completion", return_value=response_mock)

    response = await async_client.post(
        "/api/v1/breakdown",
        json={"text": "set up ci and deploy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    # Base + full estimate stands: the reconcile delta is zero.
    assert await counter_value(user["id"]) == _BASE_BALANCE + LLM_BREAKDOWN_RESERVE_TOKENS


@pytest.mark.anyio
async def test_plan_generic_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A non-provider failure inside create_plan still refunds — a ValueError
    is neither the mapped provider errors nor the RuntimeError the embeddings
    path maps, so it exercises the catch-all."""
    user = await register_user(db, async_client, "leak_pl", "leak_pl@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    # Open task required so the planner reaches the LLM call instead of the
    # D-08 short-circuit (see test_plan_provider_error_refunds_reservation).
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "plan leak task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._openai_client",
        side_effect=ValueError("unexpected boom"),
    )
    with pytest.raises(ValueError):
        await async_client.post(
            "/api/v1/plan",
            json={"available_minutes": 120},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_plan_missing_usage_keeps_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A provider that omits ``usage`` settles at the reserved amount —
    total_tokens 0 is "unmeasured", not "free"."""
    user = await register_user(db, async_client, "leak_plu", "leak_plu@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "plan usage task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"buckets": []})))],
        usage=None,
    )
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["model"] != "rule"  # real LLM path, not a short-circuit
    assert await counter_value(user["id"]) == _BASE_BALANCE + LLM_PLAN_RESERVE_TOKENS


@pytest.mark.anyio
async def test_plan_rule_short_circuit_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """The planner's rule short-circuit never calls the provider, so the
    whole estimate refunds — the missing-usage settle must not bill it."""
    user = await register_user(db, async_client, "leak_pls", "leak_pls@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)

    response = await async_client.post(
        "/api/v1/plan",
        json={"available_minutes": 120},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["model"] == "rule"
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_ask_generic_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A non-provider failure inside ask still refunds — a ValueError escapes
    the mapped handlers (ask also maps RuntimeError -> 503)."""
    user = await register_user(db, async_client, "leak_ak", "leak_ak@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "ask leak task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant.generate_answer",
        new=AsyncMock(side_effect=ValueError("unexpected boom")),
    )
    with pytest.raises(ValueError):
        await async_client.post(
            f"/api/v1/tasks/{task_resp.json()['id']}/knowledge/ask",
            json={"query": "what do I need"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_ask_missing_usage_keeps_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A provider that omits ``usage`` settles at the reserved amount — the
    same conservative rule the ask stream already applies."""
    user = await register_user(db, async_client, "leak_aku", "leak_aku@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "ask usage task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="an answer"))],
        usage=None,
    )
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)

    response = await async_client.post(
        f"/api/v1/tasks/{task_resp.json()['id']}/knowledge/ask",
        json={"query": "what do I need"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert await counter_value(user["id"]) == _BASE_BALANCE + LLM_ASK_RESERVE_TOKENS


@pytest.mark.anyio
async def test_ask_stream_prep_error_rolls_back_before_refund(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A pre-stream failure can poison the session — the catch-all must roll
    back before refunding or the refund's UPDATE dies and masks the error."""
    user = await register_user(db, async_client, "leak_sak", "leak_sak@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "stream prep task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch.object(
        KnowledgeAssistant,
        "prepare_ask_stream",
        side_effect=ValueError("db gone"),
    )
    rollback_spy = mocker.spy(AsyncSession, "rollback")
    with pytest.raises(ValueError):
        await async_client.post(
            f"/api/v1/tasks/{task_resp.json()['id']}/knowledge/ask/stream",
            json={"query": "what do I need"},
            headers={"Authorization": f"Bearer {token}"},
        )
    rollback_spy.assert_awaited()
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_voice_stt_generic_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A non-provider failure in STT still refunds the reservation."""
    user = await register_user(db, async_client, "leak_vc", "leak_vc@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    stt_client = mocker.MagicMock()
    stt_client.audio.transcriptions.create.side_effect = ValueError("unexpected boom")
    mocker.patch("app.knowledge.voice._stt_client", return_value=stt_client)

    with pytest.raises(ValueError):
        await async_client.post(
            "/api/v1/voice/plan",
            files={"audio": ("clip.webm", b"fake-audio-bytes", "audio/webm")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_voice_plan_generic_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A non-provider failure in the planner leg still refunds — the second
    provider call sits inside the same reservation window as STT."""
    user = await register_user(db, async_client, "leak_vcp", "leak_vcp@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "voice plan task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    stt_client = mocker.MagicMock()
    stt_client.audio.transcriptions.create.return_value = SimpleNamespace(text="plan tonight")
    mocker.patch("app.knowledge.voice._stt_client", return_value=stt_client)
    mocker.patch(
        "app.knowledge.assistant._openai_client",
        side_effect=ValueError("unexpected boom"),
    )
    with pytest.raises(ValueError):
        await async_client.post(
            "/api/v1/voice/plan",
            files={"audio": ("clip.webm", b"fake-audio-bytes", "audio/webm")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_voice_plan_missing_usage_keeps_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A provider that omits ``usage`` on the plan leg settles at the reserve."""
    user = await register_user(db, async_client, "leak_vcu", "leak_vcu@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "voice usage task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    stt_client = mocker.MagicMock()
    stt_client.audio.transcriptions.create.return_value = SimpleNamespace(text="plan tonight")
    mocker.patch("app.knowledge.voice._stt_client", return_value=stt_client)
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"buckets": []})))],
        usage=None,
    )
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)

    response = await async_client.post(
        "/api/v1/voice/plan",
        files={"audio": ("clip.webm", b"fake-audio-bytes", "audio/webm")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert await counter_value(user["id"]) == _BASE_BALANCE + LLM_VOICE_RESERVE_TOKENS


@pytest.mark.anyio
async def test_voice_rule_short_circuit_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """Voice into an empty pool short-circuits the planner (no provider
    call) — the whole estimate still refunds."""
    user = await register_user(db, async_client, "leak_vcs", "leak_vcs@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    stt_client = mocker.MagicMock()
    stt_client.audio.transcriptions.create.return_value = SimpleNamespace(text="plan tonight")
    mocker.patch("app.knowledge.voice._stt_client", return_value=stt_client)

    response = await async_client.post(
        "/api/v1/voice/plan",
        files={"audio": ("clip.webm", b"fake-audio-bytes", "audio/webm")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["plan"]["model"] == "rule"
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_voice_persist_failure_keeps_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A DB failure persisting telemetry AFTER the provider call must not
    refund — STT + plan tokens were really consumed, so the estimate stands
    as the bill (same convention as breakdown/import)."""
    user = await register_user(db, async_client, "persist_vc", "persist_vc@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    stt_client = mocker.MagicMock()
    stt_client.audio.transcriptions.create.return_value = SimpleNamespace(text="plan tonight")
    mocker.patch("app.knowledge.voice._stt_client", return_value=stt_client)
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"buckets": []})))],
        usage=None,
    )
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)
    mocker.patch(
        "app.api.routers.voice.create_voice_answer",
        new=AsyncMock(side_effect=ValueError("db gone")),
    )

    with pytest.raises(ValueError):
        await async_client.post(
            "/api/v1/voice/plan",
            files={"audio": ("clip.webm", b"fake-audio-bytes", "audio/webm")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert await counter_value(user["id"]) == _BASE_BALANCE + LLM_VOICE_RESERVE_TOKENS


@pytest.mark.anyio
async def test_ask_stream_provider_error_after_generation_settles_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A provider error AFTER generation started consumed billable tokens —
    the stream settles at the reserve instead of refunding the estimate."""
    user = await register_user(db, async_client, "strm_set", "strm_set@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "stream settle task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)

    stream_ctx = SimpleNamespace(generation_started=False)
    mocker.patch.object(
        KnowledgeAssistant,
        "prepare_ask_stream",
        new=AsyncMock(return_value=stream_ctx),
    )

    async def fail_after_generation(self: Any, db: Any, ctx: Any) -> Any:
        ctx.generation_started = True
        raise openai.APIError("mid-stream boom", request=None, body=None)
        yield  # pragma: no cover - keeps this an async generator

    mocker.patch.object(KnowledgeAssistant, "ask_stream", fail_after_generation)

    response = await async_client.post(
        f"/api/v1/tasks/{task_resp.json()['id']}/knowledge/ask/stream",
        json={"query": "what do I need"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "provider_error" in response.text
    assert await counter_value(user["id"]) == _BASE_BALANCE + LLM_ASK_RESERVE_TOKENS


@pytest.mark.anyio
async def test_ask_stream_provider_error_before_generation_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A provider error BEFORE generation started consumed nothing — the
    estimate still refunds."""
    user = await register_user(db, async_client, "strm_ref", "strm_ref@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)
    task_resp = await async_client.post(
        "/api/v1/tasks/",
        json={"title": "stream refund task"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_resp.status_code == 201
    await seed_reservation(db, user["id"], _BASE_BALANCE)

    stream_ctx = SimpleNamespace(generation_started=False)
    mocker.patch.object(
        KnowledgeAssistant,
        "prepare_ask_stream",
        new=AsyncMock(return_value=stream_ctx),
    )

    async def fail_before_generation(self: Any, db: Any, ctx: Any) -> Any:
        raise openai.APIError("pre-flight boom", request=None, body=None)
        yield  # pragma: no cover - keeps this an async generator

    mocker.patch.object(KnowledgeAssistant, "ask_stream", fail_before_generation)

    response = await async_client.post(
        f"/api/v1/tasks/{task_resp.json()['id']}/knowledge/ask/stream",
        json={"query": "what do I need"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "provider_error" in response.text
    assert await counter_value(user["id"]) == _BASE_BALANCE
