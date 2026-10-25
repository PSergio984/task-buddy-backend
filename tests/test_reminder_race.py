"""Race regression: reminder sweep vs manual edits — no lost update.

Pass condition (RELI-03 race target 3):
    After interleaved execution of reminder sweeps (_process_reminders_async,
    senders mocked) and M concurrent manual content edits through the real
    API, (1) NO exception escapes either path; (2) every manual write is
    server-stamped with updated_at and the surviving field value equals the
    latest write by updated_at ordering — i.e. a manual value survives iff
    its write lands at-or-after the newest write, and the sweep's
    read-modify-write window never reverts newer content; (3) the task row
    stays consistent (no null/partial fields) and notification rows reference
    intact task state. Deterministic sub-case: an edit issued strictly AFTER
    a completed sweep round persists untouched through the NEXT sweep round.

Limitation: asyncio.gather exercises await-point interleaving deterministically
(single event loop; aiosqlite funnels writes through one connection queue).
The logic under test is dialect-independent — the Postgres CI leg covers DDL
separately. This is not an OS-thread race proof. No artificial delays or
wall-clock/timing assertions are used anywhere in this file.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.task import Task
from app.tasks import _process_reminders_async
from tests.conftest import TestSessionLocal

N_SWEEPS = 3
N_EDITS = 8


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


@pytest.mark.anyio
async def test_reminder_sweep_vs_manual_edits_no_lost_update(
    db: AsyncSession,
    confirmed_user: dict[str, Any],
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    """Interleave N sweeps with M manual edits; latest-by-updated_at write wins."""
    user_id = confirmed_user["id"]

    # Senders mocked (no network/email side effects possible in this run);
    # they remain await points so the sweep genuinely interleaves.
    mocker.patch("app.tasks._send_push_notification_async")
    mocker.patch("app.tasks._send_confirmation_email_async")

    # One task inside the REMINDER_DUE window ([now-1m, now+1m]).
    task = Task(
        title="Race Target Task",
        description="stable description",
        user_id=user_id,
        due_date=datetime.now(timezone.utc),
        completed=False,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    task_id = task.id

    # Manual traffic: each call carries a fresh distinct title.
    titles = [f"Manual Edit {i}" for i in range(N_EDITS)]

    async def run_sweep() -> None:
        await _process_reminders_async()

    async def manual_edit(title: str) -> Any:
        return await authenticated_async_client.put(
            f"/api/v1/tasks/{task_id}", json={"title": title}
        )

    outcomes = await asyncio.gather(
        *([run_sweep() for _ in range(N_SWEEPS)] + [manual_edit(t) for t in titles]),
        return_exceptions=True,
    )

    # Pass condition 1: zero exceptions escaped either path.
    escaped = [o for o in outcomes if isinstance(o, BaseException)]
    assert not escaped, f"Exceptions escaped the interleave: {escaped!r}"

    edit_responses = outcomes[N_SWEEPS:]
    for resp in edit_responses:
        assert resp.status_code == 200, f"Manual edit failed: {getattr(resp, 'text', resp)}"

    # Pass condition 2 (LWW-on-timestamp): the surviving title is the one from
    # the write with the maximum server-stamped updated_at (ties collapse to a
    # candidate set). A sweep-side clobber would surface here as an older or
    # foreign value.
    stamped = [(r.json()["updated_at"], r.json()["title"]) for r in edit_responses]
    max_ts = max(_parse_ts(ts) for ts, _ in stamped)
    newest_titles = {title for ts, title in stamped if _parse_ts(ts) == max_ts}

    async with TestSessionLocal() as fresh:  # fresh session — post-commit read
        row = (await fresh.execute(select(Task).where(Task.id == task_id))).scalar_one()
        notifications = (
            (await fresh.execute(select(Notification).where(Notification.task_id == task_id)))
            .scalars()
            .all()
        )

    # Pass condition 2 continued: final value == latest write; row intact.
    assert row.title in newest_titles, (
        f"Lost update: final title {row.title!r} not among newest writes {newest_titles!r}"
    )
    assert row.description == "stable description"
    assert row.user_id == user_id
    assert row.completed is False

    # Pass condition 3: notification bookkeeping references intact task state.
    assert len(notifications) >= 1, "Sweep produced no notification for the due-window task"
    for n in notifications:
        assert n.task_id == task_id
        assert n.title
        assert n.message


@pytest.mark.anyio
async def test_manual_edit_after_completed_sweep_survives_next_round(
    db: AsyncSession,
    confirmed_user: dict[str, Any],
    authenticated_async_client: AsyncClient,
    mocker: Any,
) -> None:
    """Deterministic ordering: a post-round edit is never reverted by the next round."""
    user_id = confirmed_user["id"]
    mocker.patch("app.tasks._send_push_notification_async")
    mocker.patch("app.tasks._send_confirmation_email_async")

    task = Task(
        title="Before Edit",
        user_id=user_id,
        due_date=datetime.now(timezone.utc),
        completed=False,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    task_id = task.id

    # Round 1 delivers the reminder (exactly once).
    await _process_reminders_async()
    count_after_round1 = len(
        (await db.execute(select(Notification).where(Notification.task_id == task_id)))
        .scalars()
        .all()
    )
    assert count_after_round1 == 1

    # Manual edit strictly AFTER the completed sweep round.
    edit_resp = await authenticated_async_client.put(
        f"/api/v1/tasks/{task_id}", json={"title": "After Sweep Edit"}
    )
    assert edit_resp.status_code == 200

    # Next sweep round must not clobber newer content (dedupe skips delivery;
    # nothing in the read-modify-write window may resurrect older state).
    await _process_reminders_async()

    async with TestSessionLocal() as fresh:
        row = (await fresh.execute(select(Task).where(Task.id == task_id))).scalar_one()
        notifications = (
            (await fresh.execute(select(Notification).where(Notification.task_id == task_id)))
            .scalars()
            .all()
        )

    assert row.title == "After Sweep Edit", (
        f"Next sweep round reverted newer content: {row.title!r}"
    )
    assert len(notifications) == 1, f"Dedupe broke across rounds: {len(notifications)} rows"
