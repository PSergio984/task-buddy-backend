"""Pure Last-Write-Wins merge logic for the sync API.

No I/O in this module: every function is deterministic and unit-testable.
The router (app/api/routers/sync.py) loads rows, calls decide_apply, and
persists; this module only decides and shapes.
"""

from datetime import datetime

from app.schemas.sync import SyncEntity

# Mergeable payload keys per entity: every model column a client may
# overwrite. id / user_id / created_at / updated_at are server-owned and
# never mergeable (a client can never re-stamp ownership or timestamps).
MODEL_WHITELISTS: dict[SyncEntity, set[str]] = {
    SyncEntity.TASK: {
        "project_id",
        "title",
        "description",
        "completed",
        "priority",
        "due_date",
    },
    SyncEntity.SUBTASK: {
        "task_id",
        "title",
        "description",
        "completed",
        "due_date",
        "position",
    },
    SyncEntity.PROJECT: {"name", "color", "icon", "position"},
}

_TIEBREAK_NOTE = (
    "Equal timestamps resolve server-wins (change reported as conflict) so a "
    "client replay can never double-apply; the client converges on server state."
)


def decide_apply(client_ts: datetime, server_ts: datetime | None) -> bool:
    """True iff the client's change should be applied (strict LWW).

    Naive datetimes are rejected loudly rather than compared silently —
    a naive client timestamp is a 422 at the router, never a timezone bug here.
    """
    if client_ts.tzinfo is None:
        raise ValueError("client_ts must be timezone-aware")
    if server_ts is None:
        # Row absence is handled by the router as not_found; a None server
        # timestamp cannot be decided here.
        raise ValueError("server_ts must not be None; absence is not_found")
    if server_ts.tzinfo is None:
        raise ValueError("server_ts must be timezone-aware")
    if client_ts == server_ts:
        # _TIEBREAK_NOTE: documented deterministic tiebreak — server wins.
        return False
    return client_ts > server_ts


def merge_payload(payload: dict, whitelist: set[str]) -> dict:
    """Return only whitelisted, non-None payload keys. Never raises."""
    return {k: v for k, v in payload.items() if k in whitelist and v is not None}


def serialize_row(row) -> dict:
    """Serialize a row's columns to a JSON-safe dict.

    Column-only (no relationship access): lazy-loading `tags`/`subtasks`
    from a sync-loaded ORM row raises MissingGreenlet in async contexts.
    Column names match the REST response schemas' scalar wire fields;
    nested relations (e.g. TaskResponse.tags/subtasks) are intentionally
    omitted from sync payloads.
    """
    state: dict = {}
    for column in type(row).__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, datetime):
            value = value.isoformat()
        state[column.name] = value
    return state
