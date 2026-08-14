"""Integration tests for Phase 8 Memory ingest triggers (plan 08-02)."""

from datetime import datetime, timedelta
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.history import (
    backfill_history_corpus,
    create_history_knowledge,
    ingest_history_task,
)
from app.models.knowledge import KnowledgeChunk, SourceType, TaskKnowledge
from app.models.task import Task
from app.models.user import User


async def create_task(client: AsyncClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201, f"Task creation failed: {response.text}"
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


async def history_row_count(db: AsyncSession, task_id: int) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(TaskKnowledge)
            .where(TaskKnowledge.task_id == task_id)
        )
    ).scalar_one()


async def chunk_count_for_task(db: AsyncSession, task_id: int) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(KnowledgeChunk).where(
                KnowledgeChunk.task_id == task_id
            )
        )
    ).scalar_one()


@pytest.mark.anyio
async def test_history_dedupe_guard_skips_existing_row(
    db: AsyncSession, mocker: object
) -> None:
    user = User(username="hist_dedupe", email="hist_dedupe@example.com", password="x")
    db.add(user)
    await db.flush()

    created = datetime(2026, 1, 1, 10, 0)
    updated = created + timedelta(minutes=90)
    task = Task(
        title="Dedupe me",
        completed=True,
        created_at=created,
        updated_at=updated,
        user_id=user.id,
    )
    db.add(task)
    await db.flush()

    first = await create_history_knowledge(db, task)
    second = await create_history_knowledge(db, task)

    assert first is not None
    assert first.source_type == SourceType.HISTORY
    assert first.extra_metadata["duration_minutes"] == 90.0
    assert second is None
    assert await history_row_count(db, task.id) == 1


@pytest.mark.anyio
async def test_complete_task_ingests_history_row(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "hist_a", "hist_a@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    task = await create_task(
        async_client, token, {"title": "Write report", "description": "Full report"}
    )
    response = await async_client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"completed": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text

    assert await history_row_count(db, task["id"]) == 1
    row = (
        await db.execute(
            select(TaskKnowledge).where(TaskKnowledge.task_id == task["id"])
        )
    ).scalar_one()
    assert row.source_type == SourceType.HISTORY
    assert row.title == "Write report"
    assert row.content.startswith("Write report")
    assert await chunk_count_for_task(db, task["id"]) >= 1

    db_task = (
        await db.execute(select(Task).where(Task.id == task["id"]))
    ).scalar_one()
    expected = max(
        0.0,
        round((db_task.updated_at - db_task.created_at).total_seconds() / 60, 2),
    )
    assert row.extra_metadata["duration_minutes"] == expected


@pytest.mark.anyio
async def test_completion_hook_scoped_to_owner(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    owner = await register_user(db, async_client, "hist_owner", "hist_owner@example.com")
    await confirm_user(db, owner)
    owner_token = await login_user(async_client, owner)

    intruder = await register_user(db, async_client, "hist_intruder", "hist_intruder@example.com")
    await confirm_user(db, intruder)
    intruder_token = await login_user(async_client, intruder)

    task = await create_task(
        async_client, owner_token, {"title": "Private report"}
    )
    response = await async_client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"completed": True},
        headers={"Authorization": f"Bearer {intruder_token}"},
    )
    assert response.status_code == 404

    assert await history_row_count(db, task["id"]) == 0


@pytest.mark.anyio
async def test_uncomplete_deletes_history_row(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "hist_b", "hist_b@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    task = await create_task(async_client, token, {"title": "Toggle me"})
    response = await async_client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"completed": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert await history_row_count(db, task["id"]) == 1

    response = await async_client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"completed": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    assert await history_row_count(db, task["id"]) == 0
    assert await chunk_count_for_task(db, task["id"]) == 0


@pytest.mark.anyio
async def test_recomplete_reingests_fresh(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "hist_c", "hist_c@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    task = await create_task(async_client, token, {"title": "Cycle me"})
    for completed in (True, False, True):
        response = await async_client.put(
            f"/api/v1/tasks/{task['id']}",
            json={"completed": completed},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    assert await history_row_count(db, task["id"]) == 1


@pytest.mark.anyio
async def test_completed_toggle_twice_no_duplicate(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "hist_d", "hist_d@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    task = await create_task(async_client, token, {"title": "Double complete"})
    for _ in range(2):
        response = await async_client.put(
            f"/api/v1/tasks/{task['id']}",
            json={"completed": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    assert await history_row_count(db, task["id"]) == 1


@pytest.mark.anyio
async def test_edit_completed_task_keeps_snapshot(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "hist_e", "hist_e@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    task = await create_task(async_client, token, {"title": "Original title"})
    response = await async_client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"completed": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    response = await async_client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "Renamed title"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    assert await history_row_count(db, task["id"]) == 1
    row = (
        await db.execute(
            select(TaskKnowledge).where(TaskKnowledge.task_id == task["id"])
        )
    ).scalar_one()
    assert row.title == "Original title"


@pytest.mark.anyio
async def test_delete_task_cascades_history_rows_and_chunks(
    db: AsyncSession,
    async_client: AsyncClient,
    authenticated_async_client: AsyncClient,
) -> None:
    user = await register_user(db, async_client, "hist_f", "hist_f@example.com")
    await confirm_user(db, user)
    token = await login_user(async_client, user)

    task = await create_task(async_client, token, {"title": "Delete me"})
    response = await async_client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"completed": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert await history_row_count(db, task["id"]) == 1

    response = await async_client.delete(
        f"/api/v1/tasks/{task['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    assert await history_row_count(db, task["id"]) == 0
    assert await chunk_count_for_task(db, task["id"]) == 0


@pytest.mark.anyio
async def test_startup_sweep_backfills_completed_tasks(
    db: AsyncSession, mocker: object
) -> None:
    user = User(username="hist_sweep", email="hist_sweep@example.com", password="x")
    db.add(user)
    await db.flush()

    created = datetime(2026, 1, 1, 10, 0)
    updated = created + timedelta(minutes=45)
    task = Task(
        title="Backfill me",
        completed=True,
        created_at=created,
        updated_at=updated,
        user_id=user.id,
    )
    db.add(task)
    await db.flush()

    count = await backfill_history_corpus(db)

    assert count == 1
    assert await history_row_count(db, task.id) == 1
    assert await chunk_count_for_task(db, task.id) >= 1


@pytest.mark.anyio
async def test_startup_sweep_idempotent(
    db: AsyncSession, mocker: object
) -> None:
    user = User(username="hist_sweep2", email="hist_sweep2@example.com", password="x")
    db.add(user)
    await db.flush()

    created = datetime(2026, 1, 1, 10, 0)
    updated = created + timedelta(minutes=30)
    task = Task(
        title="Sweep twice",
        completed=True,
        created_at=created,
        updated_at=updated,
        user_id=user.id,
    )
    db.add(task)
    await db.flush()

    first = await backfill_history_corpus(db)
    second = await backfill_history_corpus(db)

    assert first == 1
    assert second == 0
    assert await history_row_count(db, task.id) == 1


@pytest.mark.anyio
async def test_ingest_history_task_callable(
    db: AsyncSession, mocker: object
) -> None:
    user = User(username="hist_callable", email="hist_callable@example.com", password="x")
    db.add(user)
    await db.flush()

    created = datetime(2026, 1, 1, 10, 0)
    updated = created + timedelta(minutes=20)
    task = Task(
        title="Callable task",
        completed=True,
        created_at=created,
        updated_at=updated,
        user_id=user.id,
    )
    db.add(task)
    await db.commit()

    await ingest_history_task(task.id, task.user_id)

    assert await history_row_count(db, task.id) == 1
    assert await chunk_count_for_task(db, task.id) >= 1
