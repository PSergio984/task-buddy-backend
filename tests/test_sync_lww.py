"""Unit tests for the pure LWW merge engine (app/sync/lww.py).

Permutation-determinism pass condition (RELI-03 race target 4), exercised at
the bottom of this file against the real merge loop (_merge_changes):

    For two conflicting batches A and B touching the same entity field with
    ordered client_updated_at values, every permutation produces (a) a final
    merged entity state in which the newest-timestamp write wins regardless
    of arrival order, and (b) — whenever the stale writer can never satisfy
    the conditional write under ANY ordering (its ts <= seed) — identical
    applied/conflicts/not_found partition identity across permutations, with
    the stale-write loser reported as a conflict in both orders. A conflict's
    embedded server_state is a REJECTION-TIME mirror of the row (what the
    rejected client converges on), so its content is pinned per permutation.
    When both writes postdate the seed, partitions are a deterministic,
    reproducible function of arrival order (re-running a permutation
    reproduces it exactly) and the final state still converges.

Limitation: the batch legs drive the real engine merge over aiosqlite —
await-point interleaving under a single event loop only; the merge logic
itself is pure and dialect-independent. The Postgres CI leg covers DDL
separately. This is not an OS-thread race proof, and no artificial delays or
wall-clock/timing assertions appear in this file.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select, update

from app.api.routers.sync import _merge_changes
from app.models.task import Task
from app.schemas.sync import SyncChange, SyncEntity, SyncOp, SyncRequest
from app.sync.lww import decide_apply, merge_payload, validate_payload
from tests.conftest import TestSessionLocal

UTC = timezone.utc


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 26, hour, minute, 0, tzinfo=UTC)


def test_apply_when_client_newer():
    assert decide_apply(_ts(10), _ts(9)) is True


def test_reject_when_server_newer():
    assert decide_apply(_ts(9), _ts(10)) is False


def test_equal_timestamp_tiebreak():
    # Deterministic tiebreak: server wins (documented in lww.py) — the change
    # is reported as a conflict so a client replay can never double-apply.
    assert decide_apply(_ts(10), _ts(10)) is False


def test_merge_payload_whitelist():
    whitelist = {"title", "completed"}
    payload = {
        "title": "x",
        "completed": True,
        "user_id": 999,
        "id": 5,
        "updated_at": "2026-01-01T00:00:00Z",
        "unknown_key": "dropped",
    }
    merged = merge_payload(payload, whitelist)
    assert merged == {"title": "x", "completed": True}
    # non-whitelisted keys dropped silently; unknown keys never raise
    assert "user_id" not in merged
    assert "unknown_key" not in merged


def test_merge_payload_keeps_explicit_null():
    # Explicit None passes through so a client can clear a nullable field
    # (REST parity — previously dropped, making "clear due date" impossible).
    merged = merge_payload({"due_date": None, "title": "x"}, {"due_date", "title"})
    assert merged == {"due_date": None, "title": "x"}


def test_validate_payload_accepts_valid_task():
    validate_payload(
        {
            "title": "Plan trip",
            "completed": True,
            "priority": "HIGH",
            "due_date": "2026-08-20T10:00:00+00:00",
            "project_id": 3,
            "description": None,
        },
        SyncEntity.TASK,
    )


def test_validate_payload_rejects_garbage_due_date():
    with pytest.raises(ValueError, match="invalid ISO-8601"):
        validate_payload({"due_date": "garbage"}, SyncEntity.TASK)


def test_validate_payload_rejects_wrong_type():
    with pytest.raises(ValueError, match="expected int"):
        validate_payload({"project_id": "abc"}, SyncEntity.TASK)
    with pytest.raises(ValueError, match="expected bool"):
        validate_payload({"completed": "yes"}, SyncEntity.TASK)


def test_validate_payload_rejects_unknown_priority():
    with pytest.raises(ValueError, match="priority"):
        validate_payload({"priority": "NUCLEAR"}, SyncEntity.TASK)


def test_validate_payload_rejects_null_non_nullable():
    with pytest.raises(ValueError, match="must not be null"):
        validate_payload({"completed": None}, SyncEntity.TASK)
    # nullable fields accept None
    validate_payload({"due_date": None}, SyncEntity.TASK)


def test_validate_payload_rejects_oversized_string():
    with pytest.raises(ValueError, match="exceeds"):
        validate_payload({"title": "x" * 300}, SyncEntity.TASK)


def test_validate_payload_ignores_unknown_keys():
    validate_payload({"user_id": 999, "nonsense": [1, 2]}, SyncEntity.TASK)


def test_delete_wins_when_newer():
    # Delete shares the same LWW comparison as update (router-level behavior);
    # the decision itself is: newer client timestamp wins.
    assert decide_apply(_ts(10), _ts(9)) is True


def test_delete_stale_returns_conflict():
    assert decide_apply(_ts(9), _ts(10)) is False


def test_naive_client_timestamp_raises():
    with pytest.raises(ValueError, match="timezone-aware"):
        decide_apply(datetime(2026, 8, 13, 10, 0, 0), _ts(9))


# ---------------------------------------------------------------------------
# RELI-03 race target 4: cross-batch permutation determinism over the REAL
# merge loop (_merge_changes) — the partitions (applied/conflicts/not_found)
# only exist there; a reimplementation would mock the property under proof.
# ---------------------------------------------------------------------------


async def _seed_task(user_id: int, seed_ts: datetime) -> int:
    """Reset task rows and seed one owned row stamped at ``seed_ts``."""
    async with TestSessionLocal() as s:
        await s.execute(delete(Task))
        task = Task(title="seed", description="d", user_id=user_id, completed=False)
        s.add(task)
        await s.commit()
        await s.execute(update(Task).where(Task.id == task.id).values(updated_at=seed_ts))
        await s.commit()
        return task.id


async def _run_merge(user_id: int, changes: list[SyncChange]) -> tuple[list, list, list]:
    body = SyncRequest(changes=changes)
    async with TestSessionLocal() as s:
        applied, conflicts, not_found, _high_water, _flips = await _merge_changes(
            s, user_id, body
        )
        await s.commit()
    return applied, conflicts, not_found


def _partition(applied: list, conflicts: list, not_found: list) -> tuple:
    """Normalize partitions to comparable tuples (conflict identity only).

    The ``server_state`` dict inside a conflict is deliberately excluded from
    the cross-permutation comparison: it is a rejection-time mirror of the
    row, so it legitimately differs by arrival order (see the stale-vs-fresh
    test, which pins each permutation's snapshot explicitly).
    """
    return (
        sorted(
            (a.entity.value, a.id, a.op.value, a.server_updated_at.isoformat()) for a in applied
        ),
        sorted((c.entity.value, c.id, c.op.value) for c in conflicts),
        [(n.entity.value, n.id, n.op.value) for n in not_found],
    )


async def _final_state(task_id: int) -> dict:
    async with TestSessionLocal() as s:
        row = (await s.execute(select(Task).where(Task.id == task_id))).scalar_one()
        updated_at = row.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return {"title": row.title, "updated_at": updated_at}


def _change(task_id: int, title: str, ts: datetime) -> SyncChange:
    return SyncChange(
        entity=SyncEntity.TASK,
        id=task_id,
        op=SyncOp.UPDATE,
        payload={"title": title},
        client_updated_at=ts,
    )


@pytest.mark.anyio
async def test_sync_lww_stale_batch_partitions_identical_across_permutations(
    db, confirmed_user: dict
) -> None:
    """Stale-vs-fresh batches: partitions AND final state identical for [A,B] and [B,A].

    B's timestamp predates the seed, so its conditional write can never fire —
    under any arrival order B lands in conflicts while A applies exactly once.
    This is the strongest literal form of the pass condition.
    """
    user_id = confirmed_user["id"]
    seed = _ts(10)

    def batches_for(task_id: int) -> tuple[list[SyncChange], list[SyncChange]]:
        return (
            [_change(task_id, "from-A", _ts(12))],  # fresh write
            [_change(task_id, "from-B", _ts(9))],  # stale writer (ts < seed)
        )

    # Permutation [A, B]
    task_id_ab = await _seed_task(user_id, seed)
    batch_a, batch_b = batches_for(task_id_ab)
    applied_ab, conflicts_ab, not_found_ab = await _run_merge(user_id, batch_a + batch_b)
    part_ab = _partition(applied_ab, conflicts_ab, not_found_ab)
    state_ab = await _final_state(task_id_ab)

    # Permutation [B, A] on an identically re-seeded state
    task_id_ba = await _seed_task(user_id, seed)
    batch_a, batch_b = batches_for(task_id_ba)
    applied_ba, conflicts_ba, not_found_ba = await _run_merge(user_id, batch_b + batch_a)
    part_ba = _partition(applied_ba, conflicts_ba, not_found_ba)
    state_ba = await _final_state(task_id_ba)

    # Pass condition: identical applied/conflicts/not_found partition identity
    # and identical final merged entity state across permutations.
    assert part_ab == part_ba, f"Partitions diverged across permutations:\n{part_ab}\n{part_ba}"
    assert state_ab == state_ba, f"Final states diverged:\n{state_ab}\n{state_ba}"

    # Stale-write loser reported as conflict in BOTH orders.
    assert [(c.entity.value, c.id, c.op.value) for c in conflicts_ab] == [("task", task_id_ab, "update")]
    assert [(c.entity.value, c.id, c.op.value) for c in conflicts_ba] == [("task", task_id_ba, "update")]
    assert not_found_ab == [] and not_found_ba == []

    # Final merged entity state carries the fresh write.
    assert state_ab["title"] == "from-A"
    assert state_ab["updated_at"] == _ts(12)

    # Snapshot semantics: a conflict's server_state is the row AS OF ITS
    # REJECTION — order-dependent by design (it is what the rejected client
    # converges on), while the partition identity above stays invariant.
    #   [A, B]: B rejected after A applied → mirror shows A's result.
    assert conflicts_ab[0].server_state["title"] == "from-A"
    #   [B, A]: B rejected before A ran → mirror still shows the seed row.
    assert conflicts_ba[0].server_state["title"] == "seed"


@pytest.mark.anyio
async def test_sync_lww_conflicting_fresh_batches_converge_and_replay_deterministically(
    db, confirmed_user: dict
) -> None:
    """Both-newer conflicting writes: final state converges; per-permutation replay exact."""
    user_id = confirmed_user["id"]
    seed = _ts(10)

    def batches_for(task_id: int) -> tuple[list[SyncChange], list[SyncChange]]:
        return (
            [_change(task_id, "from-A", _ts(11))],
            [_change(task_id, "from-B", _ts(12))],
        )

    # --- [A, B]: older applies first, newer supersedes ----------------------
    tid_ab = await _seed_task(user_id, seed)
    batch_a, batch_b = batches_for(tid_ab)
    part_ab = _partition(*(await _run_merge(user_id, batch_a + batch_b)))
    state_ab = await _final_state(tid_ab)
    assert len(part_ab[0]) == 2 and part_ab[1] == [], "Both writes should apply when ordered"
    assert state_ab["title"] == "from-B" and state_ab["updated_at"] == _ts(12)

    # --- [B, A]: newer applies first; stale writer arrives last → conflict --
    tid_ba = await _seed_task(user_id, seed)
    batch_a, batch_b = batches_for(tid_ba)
    applied, conflicts, not_found = await _run_merge(user_id, batch_b + batch_a)
    part_ba = _partition(applied, conflicts, not_found)
    state_ba = await _final_state(tid_ba)
    assert len(part_ba[0]) == 1 and part_ba[0][0][3] == _ts(12).isoformat()
    assert len(conflicts) == 1
    loser = conflicts[0]
    assert (loser.entity, loser.id, loser.op) == (SyncEntity.TASK, tid_ba, SyncOp.UPDATE)
    assert loser.server_state["title"] == "from-B", (
        "Conflict must carry current server state so the client converges"
    )
    assert not_found == []

    # Determinism truth 1: final merged entity state identical across perms.
    assert state_ab == state_ba

    # Determinism truth 2: re-running a permutation reproduces it exactly.
    tid_rerun = await _seed_task(user_id, seed)
    batch_a, batch_b = batches_for(tid_rerun)
    part_rerun = _partition(*(await _run_merge(user_id, batch_b + batch_a)))
    assert part_rerun == part_ba, "Same permutation replayed differently"

    # The stale writer NEVER survives in final state under any permutation.
    assert state_ba["title"] == "from-B"


@pytest.mark.anyio
async def test_sync_lww_single_batch_controls_match_permutation_winner(
    db, confirmed_user: dict
) -> None:
    """Controls: each single batch alone elects the same winner permutations converge to."""
    user_id = confirmed_user["id"]
    seed = _ts(10)

    tid_single_b = await _seed_task(user_id, seed)
    single_b = [_change(tid_single_b, "from-B", _ts(12))]
    part_b = _partition(*(await _run_merge(user_id, single_b)))
    state_b = await _final_state(tid_single_b)
    assert len(part_b[0]) == 1 and part_b[1] == [] and part_b[2] == []
    assert state_b["title"] == "from-B" and state_b["updated_at"] == _ts(12)

    tid_single_a = await _seed_task(user_id, seed)
    single_a = [_change(tid_single_a, "from-A", _ts(11))]
    part_a = _partition(*(await _run_merge(user_id, single_a)))
    state_a = await _final_state(tid_single_a)
    assert len(part_a[0]) == 1 and part_a[1] == []
    assert state_a["title"] == "from-A" and state_a["updated_at"] == _ts(11)

    # The converged winner of both-newer permutations equals the isolated [B] run.
    tid_cross = await _seed_task(user_id, seed)
    cross = [_change(tid_cross, "from-A", _ts(11)), _change(tid_cross, "from-B", _ts(12))]
    _, _, _ = await _run_merge(user_id, cross)
    state_cross_final = await _final_state(tid_cross)
    assert state_cross_final == state_b, "Permutation convergence disagrees with control [B]"
