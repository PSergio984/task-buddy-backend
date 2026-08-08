"""Tests for the database seeding script."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed import seed_data


def _sync_url(db: AsyncSession) -> str:
    """Convert the async test database URL to a sync URL for the seed script."""
    return str(db.get_bind().url).replace("+aiosqlite", "")


@pytest.mark.anyio
async def test_seed_data(async_client: AsyncClient, db: AsyncSession) -> None:
    """
    Test that the seeding script successfully populates a confirmed user,
    with retrievable tasks, projects, subtasks, and tags.
    """
    # 1. Run seed script with the test database URL
    # Convert async driver URL to sync for the seed script
    sync_url = _sync_url(db)
    seed_data(sync_url)

    # 2. Login as the seeded user
    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": "demo@example.com", "password": "password123"},
    )
    assert response.status_code == 200, "Failed to login as seeded user"
    token = response.json()["access_token"]

    # 3. Retrieve tasks
    headers = {"Authorization": f"Bearer {token}"}
    tasks_response = await async_client.get("/api/v1/tasks/", headers=headers)
    assert tasks_response.status_code == 200

    tasks = tasks_response.json()
    assert len(tasks) == 24, "Seeded user should have exactly 24 tasks"

    task_titles = [task["title"] for task in tasks]
    assert "Finalize Q3 Infrastructure Audit" in task_titles
    assert "Setup Automated Backup Logic" in task_titles

    # 4. Retrieve projects
    projects_response = await async_client.get("/api/v1/projects/", headers=headers)
    assert projects_response.status_code == 200
    projects = projects_response.json()
    assert len(projects) == 4, "Seeded user should have exactly 4 projects"


@pytest.mark.anyio
async def test_seed_data_targets_seed_email(
    async_client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seed data lands on the account named by SEED_EMAIL, not just the default."""
    sync_url = _sync_url(db)
    monkeypatch.setenv("SEED_EMAIL", "e2e@test.dev")
    seed_data(sync_url)

    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": "e2e@test.dev", "password": "password123"},
    )
    assert response.status_code == 200, "Failed to login as SEED_EMAIL user"
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    tasks_response = await async_client.get("/api/v1/tasks/", headers=headers)
    assert tasks_response.status_code == 200
    assert len(tasks_response.json()) == 24, "SEED_EMAIL user should have 24 tasks"

    # The default demo user must NOT exist — the seed targeted another account.
    demo_response = await async_client.post(
        "/api/v1/users/token",
        data={"username": "demo@example.com", "password": "password123"},
    )
    assert demo_response.status_code == 401


@pytest.mark.anyio
async def test_seed_password_override(
    async_client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED_PASSWORD controls the credential of a freshly seeded account."""
    sync_url = _sync_url(db)
    monkeypatch.setenv("SEED_EMAIL", "e2e@test.dev")
    monkeypatch.setenv("SEED_PASSWORD", "E2eTest!2026")
    seed_data(sync_url)

    response = await async_client.post(
        "/api/v1/users/token",
        data={"username": "e2e@test.dev", "password": "E2eTest!2026"},
    )
    assert response.status_code == 200, "Failed to login with SEED_PASSWORD"
    # The default password must not work.
    default_response = await async_client.post(
        "/api/v1/users/token",
        data={"username": "e2e@test.dev", "password": "password123"},
    )
    assert default_response.status_code == 401


def test_seed_rejects_malformed_seed_email(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed SEED_EMAIL fails closed before any database work."""
    sync_url = _sync_url(db)
    monkeypatch.setenv("SEED_EMAIL", "not-an-email")
    with pytest.raises(SystemExit):
        seed_data(sync_url)

    monkeypatch.setenv("SEED_EMAIL", "@nodomain")
    with pytest.raises(SystemExit):
        seed_data(sync_url)


def test_seed_fails_closed_on_non_seed_domain(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SEED_EMAIL pointing at a real-looking domain refuses to seed without SEED_ALLOWED."""
    sync_url = _sync_url(db)
    monkeypatch.setenv("SEED_EMAIL", "admin@katahira.com")
    with pytest.raises(SystemExit):
        seed_data(sync_url)

    # The same email is accepted when the override is explicit.
    monkeypatch.setenv("SEED_ALLOWED", "true")
    seed_data(sync_url)
