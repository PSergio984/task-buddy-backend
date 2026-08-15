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

# Nullable mergeable fields: an explicit None clears the column (REST parity).
# Everything else must carry a value (validation rejects None).
_NULLABLE: dict[SyncEntity, set[str]] = {
    SyncEntity.TASK: {"project_id", "description", "due_date"},
    SyncEntity.SUBTASK: {"description", "due_date"},
    SyncEntity.PROJECT: set(),
}

# Expected Python types per mergeable field (payloads arrive as raw JSON).
_FIELD_TYPES: dict[SyncEntity, dict[str, tuple[type, ...]]] = {
    SyncEntity.TASK: {
        "project_id": (int,),
        "title": (str,),
        "description": (str,),
        "completed": (bool,),
        "priority": (str,),
        "due_date": (str,),
    },
    SyncEntity.SUBTASK: {
        "task_id": (int,),
        "title": (str,),
        "description": (str,),
        "completed": (bool,),
        "due_date": (str,),
        "position": (int,),
    },
    SyncEntity.PROJECT: {"name": (str,), "color": (str,), "icon": (str,), "position": (int,)},
}

_STRING_LIMITS: dict[SyncEntity, dict[str, int]] = {
    SyncEntity.TASK: {"title": 255, "description": 10000, "priority": 16},
    SyncEntity.SUBTASK: {"title": 255, "description": 10000},
    SyncEntity.PROJECT: {"name": 100, "color": 50, "icon": 50},
}

_PRIORITIES = {"LOW", "MEDIUM", "HIGH"}

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
    """Return only whitelisted payload keys.

    Explicit None values pass through so a client can clear a nullable field
    (e.g. due_date: null); non-nullable None was already rejected by
    validate_payload. Never raises.
    """
    return {k: v for k, v in payload.items() if k in whitelist}


def _validate_field(entity: SyncEntity, key: str, value: object) -> None:
    """Validate one mergeable field's value; raise ValueError when invalid."""
    if value is None:
        if key not in _NULLABLE[entity]:
            raise ValueError(f"{entity.value}.{key}: must not be null")
        return
    expected = _FIELD_TYPES[entity][key]
    if not isinstance(value, expected):
        raise ValueError(
            f"{entity.value}.{key}: expected {expected[0].__name__}, got {type(value).__name__}"
        )
    if isinstance(value, str):
        _validate_string_field(entity, key, value)


def _validate_string_field(entity: SyncEntity, key: str, value: str) -> None:
    """Validate length and format constraints for string fields."""
    limit = _STRING_LIMITS[entity].get(key)
    if limit is not None and len(value) > limit:
        raise ValueError(f"{entity.value}.{key}: exceeds {limit} chars")
    if key == "due_date":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{entity.value}.{key}: invalid ISO-8601 datetime") from exc
    if key == "priority" and value not in _PRIORITIES:
        raise ValueError(f"{entity.value}.{key}: must be one of {sorted(_PRIORITIES)}")


def validate_payload(payload: dict, entity: SyncEntity) -> None:
    """Raise ValueError on the first invalid mergeable field.

    Sync payloads bypass the REST pydantic schemas; without this gate a
    garbage value (e.g. ``due_date: "nonsense"``) either 500s on the Postgres
    bind or is silently stored on SQLite — divergent prod-vs-test behavior.
    Only whitelisted fields are checked; unknown keys are ignored by the merge.
    """
    for key, value in payload.items():
        if key in MODEL_WHITELISTS[entity]:
            _validate_field(entity, key, value)


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
