"""Shared helpers for Phase 5 sync tests (test_sync_api, test_sync_schema)."""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

from httpx import AsyncClient

UTC = timezone.utc


def ts_ahead(hours_ahead: float) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours_ahead)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_task(client: AsyncClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/api/v1/tasks/", json=body, headers=auth(token))
    assert response.status_code == 201, f"Task creation failed: {response.text}"
    return cast(dict[str, Any], response.json())


async def create_subtask(client: AsyncClient, token: str, task_id: int) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/tasks/subtask",
        json={"title": "Child", "task_id": task_id},
        headers=auth(token),
    )
    assert response.status_code == 201, f"Subtask creation failed: {response.text}"
    return cast(dict[str, Any], response.json())
