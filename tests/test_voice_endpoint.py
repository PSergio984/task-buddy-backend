"""Tests for POST /api/v1/voice/plan (guards, STT, plan, telemetry)."""

import json
from types import SimpleNamespace
from typing import Any, cast

import httpx
import openai
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.assistant import AssistantNotConfiguredError
from app.knowledge.voice import MAX_AUDIO_BYTES, WHISPER_MODEL
from app.models.plan import PlanAnswer
from app.models.user import User
from app.models.voice import VoiceAnswer

TRANSCRIPT = "what should i work on tonight"


async def _confirmed_user(
    db: AsyncSession, client: AsyncClient, username: str
) -> tuple[dict[str, Any], str]:
    response = await client.post(
        "/api/v1/users/register",
        json={"username": username, "email": f"{username}@example.com", "password": "testpassword"},
    )
    assert response.status_code == 201, response.text

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


def _mock_stt(mocker: Any, text: str) -> Any:
    """Patch the STT client factory with a fake returning `text`."""
    client = mocker.MagicMock()
    client.audio.transcriptions.create.return_value = SimpleNamespace(text=text)
    patch = mocker.patch("app.knowledge.voice._stt_client", return_value=client)
    patch.client = client
    return patch


def _mock_plan_llm(mocker: Any, json_payload: dict[str, Any]) -> Any:
    """Patch the assistant client factory (planner resolves it at call time)."""
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(json_payload)))],
        usage=usage,
    )
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    return mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)


async def _create_task(client: AsyncClient, token: str, title: str) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/tasks/", json={"title": title}, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _files(data: bytes = b"fake-audio-bytes") -> dict[str, Any]:
    return {"audio": ("clip.webm", data, "audio/webm")}


@pytest.mark.anyio
async def test_voice_plan_success_returns_transcript_and_plan(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user, token = await _confirmed_user(db, async_client, "vc_ok")
    task = await _create_task(async_client, token, "Write voice tests")
    stt = _mock_stt(mocker, TRANSCRIPT)
    _mock_plan_llm(
        mocker,
        {
            "buckets": [
                {
                    "period": "tonight",
                    "tasks": [
                        {"task_id": task["id"], "reason": "due tonight", "effort_minutes": 30}
                    ],
                }
            ]
        },
    )

    response = await async_client.post(
        "/api/v1/voice/plan",
        files=_files(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == TRANSCRIPT
    assert body["plan"]["buckets"][0]["period"] == "tonight"
    assert body["plan"]["buckets"][0]["tasks"][0]["task_id"] == task["id"]
    assert body["plan"]["buckets"][0]["tasks"][0]["reason"] == "due tonight"

    # One Groq STT call with the pinned whisper model and the uploaded bytes
    stt.client.audio.transcriptions.create.assert_called_once()
    kwargs = stt.client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["model"] == WHISPER_MODEL
    assert kwargs["file"][1] == b"fake-audio-bytes"

    rows = (await db.execute(select(VoiceAnswer))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == user["id"]
    assert row.transcript == TRANSCRIPT
    assert row.audio_bytes == len(b"fake-audio-bytes")
    assert row.stt_model == WHISPER_MODEL
    assert row.stt_latency_ms >= 0
    # Plan LLM metrics mirrored verbatim into the voice row (zeroed short-circuit pattern)
    assert row.llm_model == "gpt-4o-mini"
    assert row.total_tokens == 120
    # mirrored verbatim from the plan response (connector-dependent)
    assert row.available_minutes == body["plan"]["available_minutes"]
    assert row.response_time_ms == body["plan"]["response_time_ms"]


@pytest.mark.anyio
async def test_voice_plan_short_circuit_persists_zeroed_row(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "vc_empty_pool")
    _mock_stt(mocker, TRANSCRIPT)

    response = await async_client.post(
        "/api/v1/voice/plan",
        files=_files(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"]["buckets"] == []
    assert body["plan"]["reason"] is not None

    rows = (await db.execute(select(VoiceAnswer))).scalars().all()
    assert len(rows) == 1
    assert rows[0].llm_model == "rule"
    assert rows[0].total_tokens == 0


@pytest.mark.anyio
async def test_voice_plan_disabled_is_404(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "vc_off")
    mocker.patch("app.api.routers.voice.VOICE_ENABLED", False)
    stt = _mock_stt(mocker, "")
    stt.client.audio.transcriptions.create.side_effect = AssertionError("STT called while disabled")

    response = await async_client.post(
        "/api/v1/voice/plan",
        files=_files(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_voice_plan_requires_auth(db: AsyncSession, async_client: AsyncClient) -> None:
    response = await async_client.post("/api/v1/voice/plan", files=_files())
    assert response.status_code == 401


@pytest.mark.anyio
async def test_voice_plan_rejects_oversized_audio_413(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "vc_big")
    stt = _mock_stt(mocker, "")
    stt.client.audio.transcriptions.create.side_effect = AssertionError("STT called")

    response = await async_client.post(
        "/api/v1/voice/plan",
        files=_files(b"x" * (MAX_AUDIO_BYTES + 1)),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 413
    rows = (await db.execute(select(VoiceAnswer))).scalars().all()
    assert rows == []


@pytest.mark.anyio
async def test_voice_plan_blank_transcript_is_422(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "vc_blank")
    _mock_stt(mocker, "   ")
    boom = mocker.patch(
        "app.knowledge.assistant._openai_client",
        side_effect=AssertionError("plan called despite blank transcript"),
    )

    response = await async_client.post(
        "/api/v1/voice/plan",
        files=_files(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert "Couldn't hear anything" in response.json()["detail"]
    boom.assert_not_called()
    rows = (await db.execute(select(VoiceAnswer))).scalars().all()
    assert rows == []


@pytest.mark.anyio
async def test_voice_plan_stt_not_configured_is_503(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "vc_nostt")
    mocker.patch(
        "app.knowledge.voice._stt_client",
        side_effect=AssistantNotConfiguredError("no groq key"),
    )

    response = await async_client.post(
        "/api/v1/voice/plan",
        files=_files(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503


@pytest.mark.anyio
async def test_voice_plan_stt_provider_error_is_503(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    _, token = await _confirmed_user(db, async_client, "vc_sttdown")
    mocker.patch(
        "app.knowledge.voice._stt_client",
        side_effect=openai.APIError(
            "upstream down",
            request=httpx.Request("POST", "https://api.groq.com"),
            body=None,
        ),
    )

    response = await async_client.post(
        "/api/v1/voice/plan",
        files=_files(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503


@pytest.mark.anyio
async def test_voice_plan_429_when_budget_exhausted(
    db: AsyncSession, async_client: AsyncClient, mocker: Any
) -> None:
    user, token = await _confirmed_user(db, async_client, "vc_budget")
    db.add(
        PlanAnswer(
            user_id=user["id"],
            answer="x",
            model="gpt-4o-mini",
            prompt_tokens=500,
            completion_tokens=0,
            total_tokens=500,
            cost_usd=0,
            response_time_ms=1,
            pool_size=1,
            available_minutes=60,
        )
    )
    await db.commit()

    mocker.patch("app.knowledge.budget.LLM_DAILY_TOKEN_BUDGET", 100)
    stt = _mock_stt(mocker, "")
    stt.client.audio.transcriptions.create.side_effect = AssertionError("STT called despite budget")

    response = await async_client.post(
        "/api/v1/voice/plan",
        files=_files(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 429
