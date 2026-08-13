"""Tests for the /api/v1/tasks/{task_id}/knowledge endpoints and knowledge models."""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    JudgeVerdict,
    KnowledgeAnswer,
    KnowledgeFeedback,
    TaskKnowledge,
)
from app.models.user import User


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


@pytest.mark.anyio
async def test_knowledge_create_requires_owned_task(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """A user cannot attach knowledge to another user's task."""
    user1_task = await create_task(async_client, logged_in_token, {"title": "User 1 task"})

    user2 = await register_user(db, async_client, "user2", "user2@example.com")
    await confirm_user(db, user2)
    token2 = await login_user(async_client, user2)

    response = await async_client.post(
        f"/api/v1/tasks/{user1_task['id']}/knowledge",
        json={"content": "someone else's notes"},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_knowledge_create_persists_fields(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """Creating a note persists source_type, title, content, and metadata."""
    user1_task = await create_task(async_client, logged_in_token, {"title": "Persist task"})

    response = await async_client.post(
        f"/api/v1/tasks/{user1_task['id']}/knowledge",
        json={
            "title": "Rubric",
            "content": "Project requires database design and SQL implementation.",
            "metadata": {"source_file": "rubric.pdf"},
        },
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["source_type"] == "note"
    assert data["title"] == "Rubric"
    assert data["content"].startswith("Project requires")
    assert data["metadata"] == {"source_file": "rubric.pdf"}
    assert data["user_id"] == confirmed_user["id"]
    assert data["task_id"] == user1_task["id"]

    stmt = select(TaskKnowledge).where(TaskKnowledge.id == data["id"])
    result = await db.execute(stmt)
    row = result.scalar_one()
    assert row.extra_metadata == {"source_file": "rubric.pdf"}


@pytest.mark.anyio
async def test_knowledge_update_ownership_denied(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """A user cannot update another user's knowledge row."""
    user1_task = await create_task(async_client, logged_in_token, {"title": "Update deny task"})
    note = await create_note(
        async_client, logged_in_token, user1_task["id"], {"content": "private note"}
    )

    user2 = await register_user(db, async_client, "user2", "user2@example.com")
    await confirm_user(db, user2)
    token2 = await login_user(async_client, user2)

    response = await async_client.put(
        f"/api/v1/tasks/{user1_task['id']}/knowledge/{note['id']}",
        json={"content": "hacked"},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_knowledge_delete_ownership_denied(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """A user cannot delete another user's knowledge row."""
    user1_task = await create_task(async_client, logged_in_token, {"title": "Delete deny task"})
    note = await create_note(
        async_client, logged_in_token, user1_task["id"], {"content": "private note"}
    )

    user2 = await register_user(db, async_client, "user2", "user2@example.com")
    await confirm_user(db, user2)
    token2 = await login_user(async_client, user2)

    response = await async_client.delete(
        f"/api/v1/tasks/{user1_task['id']}/knowledge/{note['id']}",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_knowledge_list_returns_own_only(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """Listing knowledge returns only the current user's notes for that task."""
    user1_task = await create_task(async_client, logged_in_token, {"title": "List task"})
    await create_note(async_client, logged_in_token, user1_task["id"], {"content": "note one"})
    await create_note(async_client, logged_in_token, user1_task["id"], {"content": "note two"})

    user2 = await register_user(db, async_client, "user2", "user2@example.com")
    await confirm_user(db, user2)
    token2 = await login_user(async_client, user2)
    user2_task = await create_task(async_client, token2, {"title": "User 2 task"})
    await create_note(async_client, token2, user2_task["id"], {"content": "user2 note"})

    response = await async_client.get(
        f"/api/v1/tasks/{user1_task['id']}/knowledge",
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200
    notes = response.json()
    assert len(notes) == 2
    assert {n["content"] for n in notes} == {"note one", "note two"}


@pytest.mark.anyio
async def test_knowledge_answer_and_feedback_rows_persist(
    db: AsyncSession,
    async_client: AsyncClient,
    logged_in_token: str,
    confirmed_user: dict[str, Any],
) -> None:
    """KnowledgeAnswer and KnowledgeFeedback rows persist with their fields."""
    user1_task = await create_task(async_client, logged_in_token, {"title": "Answer task"})

    answer = KnowledgeAnswer(
        user_id=confirmed_user["id"],
        task_id=user1_task["id"],
        answer="Read the rubric: database design, normalization, SQL.",
        model="gpt-4o-mini",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.0001,
        response_time_ms=123.45,
        retrieved_chunks=[{"knowledge_id": 1, "chunk_text": "rubric", "rrf_score": 0.5}],
        judge_verdict=JudgeVerdict.RELEVANT,
        judge_explanation="Answer covers the rubric requirements.",
    )
    db.add(answer)
    await db.flush()

    feedback = KnowledgeFeedback(
        user_id=confirmed_user["id"], answer_id=answer.id, rating=1, comment="helpful"
    )
    db.add(feedback)
    await db.flush()

    feedback_down = KnowledgeFeedback(
        user_id=confirmed_user["id"], answer_id=answer.id, rating=-1, comment="not helpful"
    )
    db.add(feedback_down)
    await db.flush()

    answer_id = answer.id
    await db.refresh(answer)
    await db.refresh(feedback)

    assert answer.total_tokens == 150
    assert answer.judge_verdict == JudgeVerdict.RELEVANT
    assert answer.retrieved_chunks[0]["knowledge_id"] == 1
    assert answer.created_at is not None
    assert feedback.rating == 1
    assert feedback_down.rating == -1
    assert feedback.answer_id == answer_id
    assert feedback.created_at is not None


@pytest.mark.anyio
async def test_task_knowledge_repr() -> None:
    """TaskKnowledge repr shows id and task_id only."""
    assert repr(TaskKnowledge(id=1, task_id=2, user_id=3)) == "<TaskKnowledge(id=1, task_id=2)>"
