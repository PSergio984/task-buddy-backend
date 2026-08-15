"""Endpoint tests for Phase 8 Memory API (plan 08-03)."""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeAnswer
from app.models.task import Task
from app.models.user import User


async def create_task(client: AsyncClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201, f"Task creation failed: {response.text}"
    return cast(dict[str, Any], response.json())


async def complete_task(client: AsyncClient, token: str, task_id: int) -> None:
    response = await client.put(
        f"/api/v1/tasks/{task_id}",
        json={"completed": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text


async def seed_history_task(
    client: AsyncClient, token: str, title: str, description: str = ""
) -> dict[str, Any]:
    task = await create_task(client, token, {"title": title, "description": description})
    await complete_task(client, token, task["id"])
    return task


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


async def answer_row_count(db: AsyncSession) -> int:
    return len((await db.execute(select(KnowledgeAnswer))).scalars().all())


@pytest.mark.anyio
async def test_memory_similar_owner_gate_404(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    owner = await register_user(db, async_client, "mem_owner", "mem_owner@example.com")
    await confirm_user(db, owner)
    owner_token = await login_user(async_client, owner)

    intruder = await register_user(db, async_client, "mem_intruder", "mem_intruder@example.com")
    await confirm_user(db, intruder)
    intruder_token = await login_user(async_client, intruder)

    task = await seed_history_task(async_client, owner_token, "Private plan")

    response = await async_client.post(
        f"/api/v1/tasks/{task['id']}/memory/similar",
        headers={"Authorization": f"Bearer {intruder_token}"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"
    assert await answer_row_count(db) == 0


@pytest.mark.anyio
async def test_memory_similar_returns_history_only(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "mem_a", "mem_a@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    hist1 = await seed_history_task(async_client, token, "Write SQL migration for auth")
    hist2 = await seed_history_task(async_client, token, "Write SQL migration for audit")
    note_task = await create_task(async_client, token, {"title": "Note holder"})
    response = await async_client.post(
        f"/api/v1/tasks/{note_task['id']}/knowledge",
        json={"content": "Write SQL migration for notes"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201

    query_task = await create_task(
        async_client, token, {"title": "Write SQL migration for payments"}
    )
    response = await async_client.post(
        f"/api/v1/tasks/{query_task['id']}/memory/similar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    ids = {row["id"] for row in body["similar_tasks"]}
    assert ids.issubset({hist1["id"], hist2["id"]})
    assert note_task["id"] not in ids


@pytest.mark.anyio
async def test_memory_similar_duration_minutes_present(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "mem_b", "mem_b@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    task = await seed_history_task(async_client, token, "Duration check task")

    query_task = await create_task(async_client, token, {"title": "Duration check task"})
    response = await async_client.post(
        f"/api/v1/tasks/{query_task['id']}/memory/similar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()

    db_task = (await db.execute(select(Task).where(Task.id == task["id"]))).scalar_one()
    expected = max(
        0.0,
        round((db_task.updated_at - db_task.created_at).total_seconds() / 60, 2),
    )
    assert any(
        row["id"] == task["id"] and row["duration_minutes"] == expected
        for row in body["similar_tasks"]
    )


@pytest.mark.anyio
async def test_memory_similar_excludes_query_task(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "mem_c", "mem_c@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    # The query task is itself completed, so it IS in the corpus.
    query_task = await seed_history_task(async_client, token, "Exclusion test task")

    response = await async_client.post(
        f"/api/v1/tasks/{query_task['id']}/memory/similar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(row["id"] != query_task["id"] for row in body["similar_tasks"])


@pytest.mark.anyio
async def test_memory_similar_task_level_dedupe(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "mem_d", "mem_d@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    long_description = (
        "First requirement for the report is to collect all data sources. "
        "Second requirement is to normalize every data field into a single schema. "
        "Third requirement is to validate the pipeline against known fixtures. "
        "Fourth requirement is to document every transformation step in detail. "
        "Fifth requirement is to run the full report generation end to end."
    )
    task = await seed_history_task(
        async_client, token, "Quarterly report generation", long_description
    )

    query_task = await create_task(async_client, token, {"title": "Quarterly report generation"})
    response = await async_client.post(
        f"/api/v1/tasks/{query_task['id']}/memory/similar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()

    matches = [row for row in body["similar_tasks"] if row["id"] == task["id"]]
    assert len(matches) == 1


@pytest.mark.anyio
async def test_memory_similar_response_time_ms_present(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "mem_e", "mem_e@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    await seed_history_task(async_client, token, "Latency probe task")

    query_task = await create_task(async_client, token, {"title": "Latency probe task"})
    response = await async_client.post(
        f"/api/v1/tasks/{query_task['id']}/memory/similar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["response_time_ms"], float)
    assert body["response_time_ms"] >= 0


@pytest.mark.anyio
async def test_memory_similar_persists_zeroed_answer_row(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "mem_f", "mem_f@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    await seed_history_task(async_client, token, "Zeroed row task")

    query_task = await create_task(async_client, token, {"title": "Zeroed row task"})
    response = await async_client.post(
        f"/api/v1/tasks/{query_task['id']}/memory/similar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    answers = (await db.execute(select(KnowledgeAnswer))).scalars().all()
    assert len(answers) == 1
    answer = answers[0]
    assert answer.model == "retrieval"
    assert answer.answer == ""
    assert answer.prompt_tokens == 0
    assert answer.completion_tokens == 0
    assert answer.total_tokens == 0
    assert answer.cost_usd == 0
    assert answer.task_id == query_task["id"]
    assert answer.user_id == user["id"]
    for citation in answer.retrieved_chunks:
        assert "knowledge_id" in citation
        assert "chunk_text" in citation
        assert "rrf_score" in citation


@pytest.mark.anyio
async def test_memory_similar_missing_key_is_503_not_500(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
    mocker: object,
) -> None:
    """Missing OpenAI key must surface as 503 (like ask/plan), never a 500.

    The embedding path raises RuntimeError when the key is unset; memory/similar
    used to let it escape as a 500 (observed live 2026-08-15 during dogfood).
    """
    user = await register_user(db, async_client, "mem_g", "mem_g@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    query_task = await create_task(async_client, token, {"title": "503 probe task"})

    async def boom(texts: list[str]) -> Any:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    mocker.patch("app.knowledge.retrieval.aembed_texts", side_effect=boom)

    response = await async_client.post(
        f"/api/v1/tasks/{query_task['id']}/memory/similar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AI assistant not configured"
