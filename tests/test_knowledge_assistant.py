"""Tests for the instrumented knowledge assistant (generate + judge + ask/feedback).

All LLM calls are mocked (offline mode) — the suite passes with no
OPENAI_API_KEY set. The key-check lives in ``_openai_client`` and is bypassed
by mocking either that function or ``generate_answer``/``evaluate_relevance``.
"""

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import OPENAI_MODEL
from app.crud.knowledge import create_answer
from app.knowledge.assistant import (
    LLMCallRecord,
    RelevanceVerdict,
    evaluate_relevance,
    generate_answer,
)
from app.knowledge.cost import calculate_cost
from app.models.knowledge import (
    JudgeVerdict,
    KnowledgeAnswer,
    KnowledgeFeedback,
)
from app.models.user import User

EXPECTED_RECORD_FIELDS = [
    "model",
    "prompt",
    "instructions",
    "answer",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "response_time",
    "cost",
    "timestamp",
]


async def create_task(client: AsyncClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201, f"Task creation failed: {response.text}"
    return cast(dict[str, Any], response.json())


async def create_note(
    client: AsyncClient, token: str, task_id: int, body: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/tasks/{task_id}/knowledge",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, f"Note creation failed: {response.text}"
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


def fake_chat_completion(content: str, prompt_tokens: int, completion_tokens: int) -> Any:
    """A minimal ChatCompletion-shaped object for mocked OpenAI responses."""
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


def make_fake_record(answer: str) -> LLMCallRecord:
    return LLMCallRecord(
        model=OPENAI_MODEL,
        prompt="generation prompt",
        instructions="assistant system prompt",
        answer=answer,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        response_time=0.4,
        cost=calculate_cost(100, 20),
    )


def test_llm_call_record_fields() -> None:
    """LLMCallRecord replicates the RESEARCH §6 field list with a default timestamp."""
    record = LLMCallRecord(
        model="gpt-4o-mini",
        prompt="p",
        instructions="i",
        answer="a",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        response_time=0.3,
        cost=0.0001,
    )
    assert list(record.__dataclass_fields__.keys()) == EXPECTED_RECORD_FIELDS
    assert isinstance(record.timestamp, datetime)


def test_calculate_cost_pricing_map() -> None:
    """calculate_cost prices per the config-driven gpt-4o-mini map (RESEARCH §8)."""
    assert calculate_cost(3000, 200) == 0.00057
    assert calculate_cost(0, 0) == 0.0


@pytest.mark.anyio
async def test_generate_answer_returns_metrics(mocker: Any) -> None:
    """generate_answer fills a full LLMCallRecord from the mocked response usage."""
    fake_response = fake_chat_completion("You need the rubric.", 100, 20)
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)

    answer, record = await generate_answer(
        "Finish database project", "Design the ER diagram", [{"chunk_id": 1, "text": "rubric"}]
    )

    assert answer == "You need the rubric."
    assert record.model == OPENAI_MODEL
    assert record.prompt_tokens == 100
    assert record.completion_tokens == 20
    assert record.total_tokens == 120
    assert record.cost == calculate_cost(100, 20)
    assert record.response_time >= 0


@pytest.mark.anyio
async def test_generate_answer_persists_answer_row(db: AsyncSession) -> None:
    """create_answer round-trips metrics + citations into a KnowledgeAnswer row."""
    user = User(username="u1", email="u1@example.com", password="x")
    db.add(user)
    await db.flush()
    from app.models.task import Task

    task = Task(title="t1", user_id=user.id)
    db.add(task)
    await db.flush()

    record = make_fake_record("You need the rubric.")
    row = await create_answer(
        db,
        user_id=user.id,
        task_id=task.id,
        answer_text="You need the rubric.",
        record=record,
        retrieved_chunks=[
            {"knowledge_id": 1, "chunk_text": "rubric", "rrf_score": 0.5},
        ],
        judge_label="RELEVANT",
        judge_explanation="Covers the rubric.",
    )
    await db.flush()

    loaded = (
        await db.execute(select(KnowledgeAnswer).where(KnowledgeAnswer.id == row.id))
    ).scalar_one()
    assert loaded.model == OPENAI_MODEL
    assert loaded.prompt_tokens == 100
    assert loaded.completion_tokens == 20
    assert loaded.total_tokens == 120
    assert loaded.judge_verdict == JudgeVerdict.RELEVANT
    assert loaded.judge_explanation == "Covers the rubric."
    assert loaded.retrieved_chunks[0]["knowledge_id"] == 1
    assert loaded.retrieved_chunks[0]["chunk_text"] == "rubric"
    assert loaded.retrieved_chunks[0]["rrf_score"] == 0.5


@pytest.mark.anyio
async def test_judge_verdict_labels_and_explanation(mocker: Any) -> None:
    """Valid judge JSON parses into RelevanceVerdict; malformed JSON degrades."""
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = fake_chat_completion(
        json.dumps({"relevance": "RELEVANT", "explanation": "Covers the requirements."}), 400, 80
    )
    mocker.patch("app.knowledge.assistant._openai_client", return_value=fake_client)

    label, explanation = await evaluate_relevance(
        "question", "answer", [{"knowledge_id": 1, "chunk_text": "c", "rrf_score": 0.5}]
    )
    assert label == "RELEVANT"
    assert explanation == "Covers the requirements."

    verdict = RelevanceVerdict(relevance="PARTLY_RELEVANT", explanation="partial")
    assert verdict.relevance in {"RELEVANT", "PARTLY_RELEVANT", "NON_RELEVANT"}

    # Malformed JSON falls back without raising.
    fake_client.chat.completions.create.return_value = fake_chat_completion("not json", 400, 80)
    label2, explanation2 = await evaluate_relevance("question", "answer", [])
    assert label2 == "PARTLY_RELEVANT"
    assert explanation2 == "judge parse failure"


@pytest.mark.anyio
async def test_ask_endpoint_returns_answer_with_citations(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
    mocker: Any,
) -> None:
    """POST /tasks/{id}/knowledge/ask returns answer + citations + metrics + a DB row."""
    task = await create_task(async_client, logged_in_token, {"title": "Database project"})
    await create_note(
        async_client,
        logged_in_token,
        task["id"],
        {
            "content": (
                "Database project rubric: design the ER diagram with at least 8 entities, "
                "normalize to 3NF, implement the SQL schema with constraints and indexes."
            )
        },
    )

    fake_record = make_fake_record("You need the rubric and the ER diagram.")
    mocker.patch(
        "app.knowledge.assistant.generate_answer",
        new=AsyncMock(return_value=("You need the rubric and the ER diagram.", fake_record)),
    )
    mocker.patch(
        "app.knowledge.assistant.evaluate_relevance",
        new=AsyncMock(return_value=("RELEVANT", "Covers the rubric.")),
    )

    response = await async_client.post(
        f"/api/v1/tasks/{task['id']}/knowledge/ask",
        json={},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["answer"] == "You need the rubric and the ER diagram."
    assert data["citations"]
    assert all(c["knowledge_id"] for c in data["citations"])
    assert isinstance(data["cost_usd"], (int, float))
    assert data["judge_verdict"] in {"RELEVANT", "PARTLY_RELEVANT", "NON_RELEVANT"}
    assert data["judge_explanation"] == "Covers the rubric."
    assert data["answer_id"]

    rows = (
        (await db.execute(select(KnowledgeAnswer).where(KnowledgeAnswer.task_id == task["id"])))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].judge_verdict == JudgeVerdict.RELEVANT


@pytest.mark.anyio
async def test_ask_endpoint_rejects_foreign_task(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """A user cannot ask on another user's task (404 before any LLM call)."""
    task = await create_task(async_client, logged_in_token, {"title": "User 1 task"})

    user2 = await register_user(db, async_client, "user2", "user2@example.com")
    await confirm_user(db, user2)
    token2 = await login_user(async_client, user2)

    response = await async_client.post(
        f"/api/v1/tasks/{task['id']}/knowledge/ask",
        json={},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_feedback_rating_persists(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """+1/-1 feedback persists and joins to the answer row; invalid rating 422s."""
    task = await create_task(async_client, logged_in_token, {"title": "Feedback task"})
    answer = KnowledgeAnswer(
        user_id=confirmed_user["id"],
        task_id=task["id"],
        answer="You need the rubric.",
        model=OPENAI_MODEL,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        cost_usd=0.0001,
        response_time_ms=100.0,
        retrieved_chunks=[],
        judge_verdict=JudgeVerdict.RELEVANT,
    )
    db.add(answer)
    await db.commit()
    answer_id = answer.id

    response = await async_client.post(
        f"/api/v1/tasks/{task['id']}/knowledge/answers/{answer_id}/feedback",
        json={"rating": 1},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["rating"] == 1
    assert data["answer_id"] == answer_id

    row = (
        await db.execute(select(KnowledgeFeedback).where(KnowledgeFeedback.answer_id == answer_id))
    ).scalar_one()
    assert row.rating == 1

    invalid = await async_client.post(
        f"/api/v1/tasks/{task['id']}/knowledge/answers/{answer_id}/feedback",
        json={"rating": 5},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert invalid.status_code == 422


@pytest.mark.anyio
async def test_feedback_rejects_foreign_answer(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """A user cannot rate another user's answer (404)."""
    task = await create_task(async_client, logged_in_token, {"title": "Foreign feedback task"})
    answer = KnowledgeAnswer(
        user_id=confirmed_user["id"],
        task_id=task["id"],
        answer="You need the rubric.",
        model=OPENAI_MODEL,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        cost_usd=0.0001,
        response_time_ms=100.0,
        retrieved_chunks=[],
        judge_verdict=JudgeVerdict.RELEVANT,
    )
    db.add(answer)
    await db.commit()
    answer_id = answer.id

    user2 = await register_user(db, async_client, "user2", "user2@example.com")
    await confirm_user(db, user2)
    token2 = await login_user(async_client, user2)

    response = await async_client.post(
        f"/api/v1/tasks/{task['id']}/knowledge/answers/{answer_id}/feedback",
        json={"rating": -1},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_no_api_key_in_any_response(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
    mocker: Any,
) -> None:
    """No response body ever leaks an api_key/Authorization/key-shaped substring (T-7-13)."""
    key_prefix = "s" + "k-"
    task = await create_task(async_client, logged_in_token, {"title": "Database project"})
    await create_note(
        async_client,
        logged_in_token,
        task["id"],
        {"content": "Database project rubric: ER diagram and 3NF normalization."},
    )

    fake_record = make_fake_record("You need the rubric.")
    mocker.patch(
        "app.knowledge.assistant.generate_answer",
        new=AsyncMock(return_value=("You need the rubric.", fake_record)),
    )
    mocker.patch(
        "app.knowledge.assistant.evaluate_relevance",
        new=AsyncMock(return_value=("RELEVANT", "ok")),
    )

    response = await async_client.post(
        f"/api/v1/tasks/{task['id']}/knowledge/ask",
        json={},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200
    body = response.text
    lowered = body.lower()
    assert "api_key" not in lowered
    assert "authorization" not in lowered
    assert key_prefix not in body


def test_llm_call_record_importable_from_neutral_module() -> None:
    """LLMCallRecord lives in a neutral module so crud needs no assistant import."""
    from app.knowledge.assistant import LLMCallRecord as AssistantRecord
    from app.knowledge.records import LLMCallRecord as RecordsRecord

    assert RecordsRecord is AssistantRecord


def test_crud_knowledge_does_not_import_assistant() -> None:
    """app.crud.knowledge must import without pulling in app.knowledge.assistant.

    ARCHITECTURE.md lists circular imports between layers as a known risk;
    the persistence layer depends on the record type, not the assistant module.
    """
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    code = (
        "import sys; "
        "import app.crud.knowledge as k; "
        "sys.exit(1 if 'app.knowledge.assistant' in sys.modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=repo_root, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_citation_normalization_single_shape() -> None:
    """One normalizer collapses the {knowledge_id, chunk_text, rrf_score} shape."""
    from app.knowledge.records import normalize_citation

    canonical = {"knowledge_id": 7, "chunk_text": "rubric text", "rrf_score": 0.5}
    assert normalize_citation(canonical) == canonical
    # text-keyed variant maps to the same canonical shape.
    assert (
        normalize_citation({"knowledge_id": 7, "text": "rubric text", "rrf_score": 0.5})
        == canonical
    )


def test_build_citations_drops_orphan_chunks() -> None:
    """A chunk with no resolved knowledge row must not mint a fabricated id."""
    from app.knowledge.records import normalize_citations

    # Raw search chunk: chunk_id only, no knowledge_id -> not a citation.
    assert normalize_citations([{"chunk_id": 999, "text": "ghost", "rrf_score": 0.1}]) == []
    # Explicit knowledge_id -> kept.
    assert normalize_citations([{"knowledge_id": 7, "chunk_text": "x", "rrf_score": 0.5}]) == [
        {"knowledge_id": 7, "chunk_text": "x", "rrf_score": 0.5}
    ]


@pytest.mark.anyio
async def test_build_citations_maps_only_resolved_chunks(
    db: AsyncSession,
) -> None:
    """_build_citations skips chunks that no longer resolve to a knowledge row."""
    from app.knowledge.assistant import KnowledgeAssistant
    from app.models.knowledge import KnowledgeChunk, TaskKnowledge
    from app.models.task import Task

    user = User(username="u9", email="u9@example.com", password="x")
    db.add(user)
    await db.flush()
    task = Task(title="t9", user_id=user.id)
    db.add(task)
    await db.flush()
    knowledge = TaskKnowledge(user_id=user.id, task_id=task.id, content="rubric")
    db.add(knowledge)
    await db.flush()

    resolved = KnowledgeChunk(
        user_id=user.id,
        task_id=task.id,
        knowledge_id=knowledge.id,
        chunk_index=0,
        content="rubric",
        embedding="[0.1,0.2,0.3]",
        content_hash="abc",
    )
    db.add(resolved)
    await db.commit()

    citations = await KnowledgeAssistant()._build_citations(
        db,
        [
            {"chunk_id": resolved.id, "text": "rubric", "rrf_score": 0.5},
            {"chunk_id": 999, "text": "ghost", "rrf_score": 0.1},
        ],
    )
    assert len(citations) == 1
    assert citations[0]["knowledge_id"] == knowledge.id
    assert citations[0]["chunk_text"] == "rubric"


def test_generation_prompt_truncates_chunk_to_1500() -> None:
    """Truncated chunk text stays within CHUNK_TEXT_LIMIT (1500)."""
    from app.knowledge.assistant import CHUNK_TEXT_LIMIT, _build_generation_prompt

    long_text = "x" * 3000
    prompt = _build_generation_prompt(
        "title", None, [{"chunk_id": 1, "text": long_text, "rrf_score": 0.5}]
    )
    chunk_line = next(line for line in prompt.splitlines() if line.startswith("[1] "))
    assert len(chunk_line) - len("[1] ") <= CHUNK_TEXT_LIMIT


def test_testconfig_feedback_rate_limit_matches_spec() -> None:
    """TestConfig RATE_LIMIT_KNOWLEDGE_FEEDBACK matches the spec (30/minute)."""
    from app.config import RATE_LIMIT_KNOWLEDGE_FEEDBACK, TestConfig

    assert TestConfig().RATE_LIMIT_KNOWLEDGE_FEEDBACK == "30/minute"
    assert RATE_LIMIT_KNOWLEDGE_FEEDBACK == "30/minute"
