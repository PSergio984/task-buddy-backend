"""API endpoints for offline sync reconciliation (strict LWW)."""

import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_SYNC
from app.dependencies import get_db
from app.limiter import limiter
from app.models.project import Project
from app.models.task import SubTask, Task
from app.models.user import User
from app.schemas.sync import (
    SyncAppliedItem,
    SyncConflictItem,
    SyncDelta,
    SyncEntity,
    SyncNotFoundItem,
    SyncOp,
    SyncRequest,
    SyncResponse,
)
from app.security import get_confirmed_user
from app.sync.lww import MODEL_WHITELISTS, decide_apply, merge_payload, serialize_row

ROUTER_TAG = "sync"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={401: {"description": "Not authenticated"}},
)

logger = logging.getLogger(__name__)

_ENTITY_MODELS: dict[SyncEntity, type[Any]] = {
    SyncEntity.TASK: Task,
    SyncEntity.SUBTASK: SubTask,
    SyncEntity.PROJECT: Project,
}


def _ensure_aware(value: datetime) -> datetime:
    """Normalize to UTC-aware.

    SQLite returns naive datetimes from server defaults; production Postgres
    returns aware. The LWW comparison requires aware input, so this shim
    coerces the DB-side value only (decide_apply still rejects naive
    client-supplied timestamps at the schema layer).
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _fk_target_owned(
    db: AsyncSession, entity: SyncEntity, merged: dict, user_id: int
) -> bool:
    """Merged foreign keys must point at the user's own rows (and exist).

    Without this, a client could attach an owned task to another user's
    project (or to a dangling id -> IntegrityError -> 500).
    """
    checks: list[tuple[type[Any], int]] = []
    if entity == SyncEntity.TASK and merged.get("project_id") is not None:
        checks.append((Project, merged["project_id"]))
    elif entity == SyncEntity.SUBTASK and merged.get("task_id") is not None:
        checks.append((Task, merged["task_id"]))
    for model, fk_id in checks:
        result = await db.execute(select(model).where(model.id == fk_id, model.user_id == user_id))
        if result.scalar_one_or_none() is None:
            return False
    return True


async def _merge_changes(
    db: AsyncSession, user_id: int, body: SyncRequest
) -> tuple[list[SyncAppliedItem], list[SyncConflictItem], list[SyncNotFoundItem], datetime | None]:
    """Apply each change under strict LWW; return results and the new high-water."""
    applied: list[SyncAppliedItem] = []
    conflicts: list[SyncConflictItem] = []
    not_found: list[SyncNotFoundItem] = []
    high_water = body.since

    for change in body.changes:
        model = _ENTITY_MODELS[change.entity]
        result = await db.execute(
            select(model).where(model.id == change.id, model.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            not_found.append(SyncNotFoundItem(entity=change.entity, id=change.id, op=change.op))
            continue

        server_ts = _ensure_aware(row.updated_at)
        if not decide_apply(change.client_updated_at, server_ts):
            conflicts.append(
                SyncConflictItem(
                    entity=change.entity,
                    id=change.id,
                    op=change.op,
                    server_state=serialize_row(row),
                )
            )
            continue

        if change.op == SyncOp.DELETE:
            await db.delete(row)
        else:
            merged = merge_payload(change.payload, MODEL_WHITELISTS[change.entity])
            if not await _fk_target_owned(db, change.entity, merged, user_id):
                # Reject the whole change (server state returned) rather than
                # partially applying or crashing with an unhandled IntegrityError.
                conflicts.append(
                    SyncConflictItem(
                        entity=change.entity,
                        id=change.id,
                        op=change.op,
                        server_state=serialize_row(row),
                    )
                )
                continue
            for key, value in merged.items():
                setattr(row, key, value)
            row.updated_at = change.client_updated_at

        applied.append(
            SyncAppliedItem(
                entity=change.entity,
                id=change.id,
                op=change.op,
                server_updated_at=change.client_updated_at,
            )
        )
        if high_water is None or change.client_updated_at > high_water:
            high_water = change.client_updated_at

    return applied, conflicts, not_found, high_water


async def _fetch_delta(db: AsyncSession, user_id: int, high_water: datetime | None) -> SyncDelta:
    """Return every row the user changed after the high-water mark."""
    delta = SyncDelta()
    targets: dict[SyncEntity, list[dict]] = {
        SyncEntity.TASK: delta.tasks,
        SyncEntity.SUBTASK: delta.subtasks,
        SyncEntity.PROJECT: delta.projects,
    }
    for entity, model in _ENTITY_MODELS.items():
        conditions = [model.user_id == user_id]
        if high_water is not None:
            conditions.append(model.updated_at > high_water)
        result = await db.execute(select(model).where(*conditions).order_by(model.updated_at))
        for row in result.scalars().all():
            targets[entity].append(serialize_row(row))
            row_ts = _ensure_aware(row.updated_at)
            if high_water is None or row_ts > high_water:
                high_water = row_ts
    return delta


@router.post("/sync", response_model=SyncResponse)
@limiter.limit(RATE_LIMIT_SYNC)
async def sync(
    request: Request,
    response: Response,
    body: SyncRequest,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncResponse:
    """Merge batched offline changes (strict LWW) and pull the delta.

    One round trip: pushes the client's offline changes and returns every row
    the user changed after the client's high-water mark.

    A `conflicts` entry means the change was NOT applied and `server_state`
    is the current row, for two causes: the change is stale (server row is
    newer — strict LWW) or it targets a foreign key the user doesn't own
    (validity rejection). In both cases the client converges on server state;
    there is no 409/manual-resolution UX.
    """
    applied, conflicts, not_found, high_water = await _merge_changes(db, current_user.id, body)
    delta = await _fetch_delta(db, current_user.id, high_water)

    if high_water is None:
        high_water = datetime.now(timezone.utc)

    await db.commit()

    logger.info(
        "POST /sync - user %s, %d changes (%d applied, %d conflicts, %d not_found), delta %d/%d/%d",
        current_user.id,
        len(body.changes),
        len(applied),
        len(conflicts),
        len(not_found),
        len(delta.tasks),
        len(delta.subtasks),
        len(delta.projects),
    )

    return SyncResponse(
        applied=applied,
        conflicts=conflicts,
        not_found=not_found,
        delta=delta,
        since=high_water,
    )
