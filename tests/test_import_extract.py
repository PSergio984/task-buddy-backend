"""Tests for POST /api/v1/import/extract (guards, success, telemetry)."""

import json
from typing import Any

import openai
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLM_IMPORT_RESERVE_TOKENS
from app.models.import_extract import ImportAnswer
from app.models.project import Project
from app.models.user import User

# Shared test helpers (cross-import precedent: test_game_notification_triggers
# pulls _make_user from test_game_notifications).
from tests.test_breakdown_endpoint import _confirmed_user, _mock_completion
from tests.test_llm_budget import _BASE_BALANCE, counter_value, seed_reservation

VALID_PAYLOAD = {
    "proposals": [
        {
            "title": "Email the venue",
            "description": "Confirm booking for Friday",
            "proposed_deadline": "2026-08-28T17:00:00+00:00",
            "priority": "HIGH",
            "suggested_project_id": None,
            "subtasks": [{"title": "Draft email"}, {"title": "Send"}],
        },
        {
            "title": "Buy snacks",
            "description": None,
            "proposed_deadline": None,
            "priority": "MEDIUM",
            "suggested_project_id": None,
            "subtasks": [],
        },
    ]
}


@pytest.mark.anyio
async def test_import_extract_success_persists_telemetry(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user, token = await _confirmed_user(db, async_client, "imp_ok")
    mock = _mock_completion(mocker, VALID_PAYLOAD)

    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "email the venue friday 5pm, buy snacks"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reason"] is None
    assert [p["title"] for p in body["proposals"]] == ["Email the venue", "Buy snacks"]
    proposal = body["proposals"][0]
    assert proposal["description"] == "Confirm booking for Friday"
    assert proposal["proposed_deadline"].startswith("2026-08-28")
    assert proposal["priority"] == "HIGH"
    assert proposal["suggested_project_id"] is None
    assert [s["title"] for s in proposal["subtasks"]] == ["Draft email", "Send"]
    assert body["proposals"][1]["priority"] == "MEDIUM"

    rows = (await db.execute(select(ImportAnswer))).scalars().all()
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
    # today's UTC date grounds relative-date resolution in the prompt
    user_prompt = mock.call_args.args[1][-1]["content"]
    assert "Today's date (UTC):" in user_prompt
    assert "email the venue friday 5pm" in user_prompt


@pytest.mark.anyio
async def test_import_extract_empty_extraction(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "imp_empty")
    _mock_completion(mocker, {"proposals": []})

    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "just musings, nothing to do"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposals"] == []
    assert body["reason"] is None


@pytest.mark.anyio
async def test_import_extract_parse_failure_returns_empty_with_reason(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "imp_bad")
    _mock_completion(mocker, {"unexpected": "shape"})

    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "anything"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["proposals"] == []
    assert body["reason"] is not None


@pytest.mark.anyio
async def test_import_extract_unparseable_deadline_dropped(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """An LLM deadline that fails ISO parsing drops to null, never 500s."""
    _, token = await _confirmed_user(db, async_client, "imp_date")
    _mock_completion(
        mocker,
        {
            "proposals": [
                {
                    "title": "Call the plumber",
                    "description": None,
                    "proposed_deadline": "next Friday",
                    "priority": "LOW",
                    "suggested_project_id": None,
                    "subtasks": [],
                }
            ]
        },
    )

    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "call the plumber next friday"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    proposal = response.json()["proposals"][0]
    assert proposal["proposed_deadline"] is None
    assert proposal["priority"] == "LOW"


@pytest.mark.anyio
async def test_import_extract_project_grounding(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """Suggested ids survive only when the user owns them; the rest null out."""
    user, token = await _confirmed_user(db, async_client, "imp_proj")
    other, _ = await _confirmed_user(db, async_client, "imp_proj_other")
    project = Project(user_id=user["id"], name="Errands")
    foreign = Project(user_id=other["id"], name="Not Mine")
    db.add_all([project, foreign])
    await db.commit()

    mock = _mock_completion(
        mocker,
        {
            "proposals": [
                {
                    "title": "Drop off package",
                    "description": None,
                    "proposed_deadline": None,
                    "priority": "MEDIUM",
                    "suggested_project_id": project.id,
                    "subtasks": [],
                },
                {
                    "title": "Invented project task",
                    "description": None,
                    "proposed_deadline": None,
                    "priority": "MEDIUM",
                    "suggested_project_id": 999999,
                    "subtasks": [],
                },
                {
                    "title": "Foreign project task",
                    "description": None,
                    "proposed_deadline": None,
                    "priority": "MEDIUM",
                    "suggested_project_id": foreign.id,
                    "subtasks": [],
                },
            ]
        },
    )

    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "errands: drop off package"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    proposals = response.json()["proposals"]
    assert proposals[0]["suggested_project_id"] == project.id
    assert proposals[1]["suggested_project_id"] is None
    assert proposals[2]["suggested_project_id"] is None  # foreign id nulled too
    # the project's id + name grounded the prompt
    user_prompt = mock.call_args.args[1][-1]["content"]
    assert "Errands" in user_prompt
    assert str(project.id) in user_prompt


@pytest.mark.anyio
async def test_import_extract_disabled_is_404(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "imp_off")
    mocker.patch("app.api.routers.import_extract.IMPORT_ENABLED", False)
    boom = mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=AssertionError("LLM called while disabled"),
    )
    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    boom.assert_not_called()


@pytest.mark.anyio
async def test_import_extract_requires_auth(db: AsyncSession, async_client: AsyncClient) -> None:
    response = await async_client.post("/api/v1/import/extract", json={"text": "hello"})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_import_extract_unconfirmed_is_403(
    db: AsyncSession, async_client: AsyncClient
) -> None:
    response = await async_client.post(
        "/api/v1/users/register",
        json={
            "username": "imp_unconf",
            "email": "imp_unconf@example.com",
            "password": "testpassword",
        },
    )
    assert response.status_code == 201, response.text
    result = await db.execute(select(User).where(User.email == "imp_unconf@example.com"))
    user_id = result.scalar_one().id
    # Login itself requires confirmation, so mint the JWT directly — the
    # token resolves fine; get_confirmed_user is what turns the 403.
    from app.security import create_access_token

    token = create_access_token(user_id)

    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_import_extract_429_when_budget_exhausted(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "imp_budget")
    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 100)
    boom = mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=AssertionError("LLM called despite budget"),
    )
    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 429
    boom.assert_not_called()


@pytest.mark.anyio
async def test_import_extract_503_when_not_configured(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user, token = await _confirmed_user(db, async_client, "_imp503")
    from app.knowledge.assistant import AssistantNotConfiguredError

    # Seeded base balance proves the refund fired — 0 -> 0 would pass even if
    # the reservation were never returned (leak regression detector).
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=AssistantNotConfiguredError("no key"),
    )
    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_import_extract_503_when_provider_down(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user, token = await _confirmed_user(db, async_client, "imp_down")
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=openai.APIError("provider boom", request=None, body=None),
    )
    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_import_extract_generic_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A non-provider failure after the reserve still refunds — otherwise the
    prepaid tokens leak until UTC rollover and phantom 429s follow."""
    user, token = await _confirmed_user(db, async_client, "imp_boom")
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=RuntimeError("unexpected boom"),
    )
    with pytest.raises(RuntimeError):
        await async_client.post(
            "/api/v1/import/extract",
            json={"text": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_import_extract_project_lookup_error_refunds_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A failure inside the reserved window before the provider call —
    here, the project lookup — still refunds; the except-clause rollback
    recovers the poisoned session so the refund itself can run."""
    user, token = await _confirmed_user(db, async_client, "imp_dbboom")
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    mocker.patch(
        "app.api.routers.import_extract.get_projects",
        side_effect=RuntimeError("db gone"),
    )
    # Class-level spy: the request's session isn't the db fixture's, and
    # SQLite can't poison a transaction — pin that the handler attempts
    # rollback before refunding (the Postgres-only recovery path).
    rollback_spy = mocker.spy(AsyncSession, "rollback")
    with pytest.raises(RuntimeError):
        await async_client.post(
            "/api/v1/import/extract",
            json={"text": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
    rollback_spy.assert_awaited()
    assert await counter_value(user["id"]) == _BASE_BALANCE


@pytest.mark.anyio
async def test_import_extract_missing_usage_keeps_reservation(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """A provider that omits ``usage`` reconciles at the reserved amount —
    conservative, the call must never become free under the daily cap."""
    user, token = await _confirmed_user(db, async_client, "imp_nouse")
    await seed_reservation(db, user["id"], _BASE_BALANCE)
    response_mock = mocker.Mock()
    response_mock.choices = [mocker.Mock()]
    response_mock.choices[0].message.content = json.dumps(VALID_PAYLOAD)
    response_mock.usage = None
    mocker.patch("app.knowledge.assistant._call_completion", return_value=response_mock)

    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "email the venue friday 5pm"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    # Base + full estimate stands: the reconcile delta is zero.
    assert await counter_value(user["id"]) == _BASE_BALANCE + LLM_IMPORT_RESERVE_TOKENS


@pytest.mark.anyio
async def test_import_extract_input_too_long_is_422(
    db: AsyncSession, async_client: AsyncClient
) -> None:
    _, token = await _confirmed_user(db, async_client, "imp_long")
    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "x" * 10_001},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_import_extract_whitespace_input_is_422(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    """Blank-but-nonempty text 422s at the schema — it must not burn an LLM
    reservation or a provider call."""
    _, token = await _confirmed_user(db, async_client, "imp_blank")
    mocker.patch(
        "app.knowledge.assistant._call_completion",
        side_effect=AssertionError("LLM called on whitespace input"),
    )
    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": "   \n\t  "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_import_extract_empty_input_is_422(
    db: AsyncSession, async_client: AsyncClient
) -> None:
    _, token = await _confirmed_user(db, async_client, "imp_short")
    response = await async_client.post(
        "/api/v1/import/extract",
        json={"text": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
