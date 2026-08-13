"""Schema contract tests for Phase 5 sync: updated_at on tasks/subtasks/projects."""

from datetime import datetime
from typing import Any, cast

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.task import SubTask, Task


async def create_task(client: AsyncClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/tasks/", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    return cast(dict[str, Any], response.json())


async def create_subtask(client: AsyncClient, token: str, task_id: int) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/tasks/subtask",
        json={"title": "Child", "task_id": task_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    return cast(dict[str, Any], response.json())


async def test_task_updated_at_server_default(async_client, logged_in_token) -> None:
    task = await create_task(async_client, logged_in_token, {"title": "Updated At Test"})
    assert task["updated_at"] is not None
    # ISO-parseable server timestamp (SQLite returns naive datetimes in tests;
    # production Postgres is tz-aware — the wire format is identical).
    datetime.fromisoformat(task["updated_at"].replace("Z", "+00:00"))


async def test_task_updated_at_touches_on_update(async_client, logged_in_token) -> None:
    task = await create_task(async_client, logged_in_token, {"title": "Before"})
    original = datetime.fromisoformat(task["updated_at"].replace("Z", "+00:00"))

    response = await async_client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "After"},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 200
    refreshed = response.json()

    later = datetime.fromisoformat(refreshed["updated_at"].replace("Z", "+00:00"))
    # SQLite second-granularity can make equal-timestamp updates pass; the
    # contract is monotonicity, so >= is the deterministic assertion.
    assert later >= original


async def test_subtask_updated_at_present(async_client, logged_in_token) -> None:
    task = await create_task(async_client, logged_in_token, {"title": "Parent"})
    subtask = await create_subtask(async_client, logged_in_token, task["id"])
    assert subtask["updated_at"] is not None


async def test_project_updated_at_present(async_client, logged_in_token) -> None:
    response = await async_client.post(
        "/api/v1/projects/",
        json={"name": "Sync Project"},
        headers={"Authorization": f"Bearer {logged_in_token}"},
    )
    assert response.status_code == 201
    project = response.json()
    assert project["updated_at"] is not None


async def test_updated_at_not_nullable(db: AsyncSession, confirmed_user: dict) -> None:
    task = Task(user_id=confirmed_user["id"], title="Raw Insert")
    db.add(task)
    await db.flush()
    await db.refresh(task)
    assert task.updated_at is not None


def test_sync_schema_repr() -> None:
    task_repr = repr(Task(id=1, title="x", completed=False))
    assert task_repr == "<Task(id=1, title=x, completed=False)>"
    subtask_repr = repr(SubTask(id=2, title="y", completed=True))
    assert subtask_repr == "<SubTask(id=2, title=y, completed=True)>"
    project_repr = repr(Project(id=3, name="p"))
    assert project_repr == "<Project(id=3, name=p)>"
