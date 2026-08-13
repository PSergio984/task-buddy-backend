"""Request/response schemas for the sync API (POST /api/v1/sync)."""

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SyncEntity(str, enum.Enum):
    TASK = "task"
    SUBTASK = "subtask"
    PROJECT = "project"


class SyncOp(str, enum.Enum):
    UPDATE = "update"
    DELETE = "delete"


def _require_tz_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("must be timezone-aware (ISO 8601 with offset)")
    return value


class SyncChange(BaseModel):
    entity: SyncEntity
    id: int = Field(..., gt=0)
    op: SyncOp
    payload: dict = Field(default_factory=dict)
    client_updated_at: datetime

    @field_validator("client_updated_at")
    @classmethod
    def validate_client_updated_at(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


class SyncRequest(BaseModel):
    since: Optional[datetime] = None
    changes: list[SyncChange] = Field(default_factory=list, max_length=500)

    @field_validator("since")
    @classmethod
    def validate_since(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return v
        return _require_tz_aware(v)


class SyncAppliedItem(BaseModel):
    entity: SyncEntity
    id: int
    op: SyncOp
    server_updated_at: datetime


class SyncConflictItem(BaseModel):
    entity: SyncEntity
    id: int
    op: SyncOp
    server_state: dict


class SyncNotFoundItem(BaseModel):
    entity: SyncEntity
    id: int
    op: SyncOp


class SyncDelta(BaseModel):
    tasks: list[dict] = Field(default_factory=list)
    subtasks: list[dict] = Field(default_factory=list)
    projects: list[dict] = Field(default_factory=list)


class SyncResponse(BaseModel):
    applied: list[SyncAppliedItem] = Field(default_factory=list)
    conflicts: list[SyncConflictItem] = Field(default_factory=list)
    not_found: list[SyncNotFoundItem] = Field(default_factory=list)
    delta: SyncDelta = Field(default_factory=SyncDelta)
    since: datetime
