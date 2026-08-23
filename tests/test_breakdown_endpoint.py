"""Tests for POST /api/v1/breakdown (guards, success, telemetry)."""

import json
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.breakdown import BreakdownAnswer
from app.models.user import User

VALID_PAYLOAD = {
    "tasks": [
        {
            "title": "Set up CI",
            "estimated_effort_minutes": 45,
            "subtasks": [{"title": "Pick provider"}, {"title": "Write workflow"}],
        },
        {"title": "Deploy", "subtasks": []},
    ]
}


async def _confirmed_user(
    db: AsyncSession, client: AsyncClient, username: str
) -> tuple[dict[str, Any], str]:
    response = await client.post(
        "/api/v1/users/register",
        json={"username": username, "email": f"{username}@example.com", "password": "testpassword"},
    )
    assert response.status_code == 201, response.text
    from sqlalchemy import update

    email = f"{username}@example.com"
    await db.execute(update(User).where(User.email == email).values(confirmed=True))
    await db.commit()
    login = await client.post(
        "/api/v1/users/token",
        data={"username": email, "password": "testpassword"},
    )
    assert login.status_code == 200, login.text
    result = await db.execute(select(User).where(User.email == email))
    user_id = result.scalar_one().id
    return {"id": user_id, "email": email}, cast(str, login.json()["access_token"])


def _mock_completion(mocker: Any, payload: dict[str, Any]) -> Any:
    """Patch the shared completion call to return a valid breakdown JSON."""
    response = mocker.Mock()
    response.choices = [mocker.Mock()]
    response.choices[0].message.content = json.dumps(payload)
    usage = mocker.Mock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.total_tokens = 150
    response.usage = usage
    return mocker.patch("app.knowledge.assistant._call_completion", return_value=response)


@pytest.mark.anyio
async def test_breakdown_success_persists_telemetry(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user, token = await _confirmed_user(db, async_client, "bd_ok")
    mock = _mock_completion(mocker, VALID_PAYLOAD)

    response = await async_client.post(
        "/api/v1/breakdown",
        json={"text": "set up ci and deploy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reason"] is None
    assert [t["title"] for t in body["tasks"]] == ["Set up CI", "Deploy"]
    assert len(body["tasks"][0]["subtasks"]) == 2

    rows = (await db.execute(select(BreakdownAnswer))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == user["id"]
    assert rows[0].total_tokens == 150
    mock.assert_called_once()
    # strict structured output requested from the provider (3rd positional arg)
    assert mock.call_args.args[2].get("type") == "json_schema"
    assert mock.call_args.args[0] == "openai/gpt-oss-120b"
    # free-tier output budget: hard completion ceiling + low reasoning effort
    assert mock.call_args.args[3] == 4096
    assert mock.call_args.args[4] == "low"


@pytest.mark.anyio
async def test_breakdown_parse_failure_returns_empty_with_reason(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "bd_bad")
    _mock_completion(mocker, {"unexpected": "shape"})

    response = await async_client.post(
        "/api/v1/breakdown",
        json={"text": "anything"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tasks"] == []
    assert body["reason"] is not None


@pytest.mark.anyio
async def test_breakdown_disabled_is_404(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "bd_off")
    mocker.patch("app.api.routers.breakdown.BREAKDOWN_ENABLED", False)
    boom = mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=AssertionError("LLM called while disabled"),
    )
    response = await async_client.post(
        "/api/v1/breakdown",
        json={"text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    boom.assert_not_called()


@pytest.mark.anyio
async def test_breakdown_requires_auth(db: AsyncSession, async_client: AsyncClient) -> None:
    response = await async_client.post("/api/v1/breakdown", json={"text": "hello"})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_breakdown_429_when_budget_exhausted(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user, token = await _confirmed_user(db, async_client, "bd_budget")
    db.add(
        BreakdownAnswer(
            user_id=user["id"],
            answer="x",
            model="m",
            prompt_tokens=500,
            completion_tokens=0,
            total_tokens=500,
            cost_usd=0,
            response_time_ms=1,
            input_chars=5,
        )
    )
    await db.commit()

    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 100)
    boom = mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=AssertionError("LLM called despite budget"),
    )
    response = await async_client.post(
        "/api/v1/breakdown",
        json={"text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 429
    boom.assert_not_called()


@pytest.mark.anyio
async def test_breakdown_503_when_not_configured(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "_bd503")
    from app.knowledge.assistant import AssistantNotConfiguredError

    mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=AssistantNotConfiguredError("no key"),
    )
    response = await async_client.post(
        "/api/v1/breakdown",
        json={"text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503


@pytest.mark.anyio
async def test_breakdown_refine_focus_reaches_prompt(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """The refine loop re-sends the original text plus the focus task title."""
    _, token = await _confirmed_user(db, async_client, "bd_refine")
    mock = _mock_completion(mocker, VALID_PAYLOAD)

    response = await async_client.post(
        "/api/v1/breakdown",
        json={
            "text": "set up ci and deploy",
            "focus_task_title": "Deploy",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    user_prompt = mock.call_args.args[1][-1]["content"]
    assert "<focus>Deploy</focus>" in user_prompt
    assert "set up ci and deploy" in user_prompt


@pytest.mark.anyio
async def test_breakdown_input_too_long_is_422(
    db: AsyncSession, async_client: AsyncClient
) -> None:
    _, token = await _confirmed_user(db, async_client, "bd_long")
    response = await async_client.post(
        "/api/v1/breakdown",
        json={"text": "x" * 10_001},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
