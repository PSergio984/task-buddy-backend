"""Wave 0 stubs for Phase 8 Memory — implemented in plans 08-01/08-02."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.history import create_history_knowledge
from app.models.knowledge import SourceType, TaskKnowledge
from app.models.task import Task
from app.models.user import User


@pytest.mark.anyio
async def test_history_dedupe_guard_skips_existing_row(
    db: AsyncSession, mocker: object
) -> None:
    user = User(username="hist", email="hist@example.com", password="x")
    db.add(user)
    await db.flush()

    created = datetime(2026, 1, 1, 10, 0)
    updated = created + timedelta(minutes=90)
    task = Task(
        title="Write report",
        description="Full report",
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

    count = (
        await db.execute(
            select(func.count())
            .select_from(TaskKnowledge)
            .where(TaskKnowledge.task_id == task.id)
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.skip(reason="implemented in plans 08-01/08-02")
def test_complete_task_ingests_history_row() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plans 08-01/08-02")
def test_completion_hook_scoped_to_owner() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plans 08-01/08-02")
def test_uncomplete_deletes_history_row() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plans 08-01/08-02")
def test_recomplete_reingests_fresh() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plans 08-01/08-02")
def test_completed_toggle_twice_no_duplicate() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plans 08-01/08-02")
def test_edit_completed_task_keeps_snapshot() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plans 08-01/08-02")
def test_delete_task_cascades_history_rows_and_chunks() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plans 08-01/08-02")
def test_startup_sweep_backfills_completed_tasks() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plans 08-01/08-02")
def test_startup_sweep_idempotent() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plans 08-01/08-02")
def test_ingest_history_task_callable() -> None:
    assert True
