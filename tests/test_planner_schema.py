"""Unit tests for the Phase 9 Planner schema layer (plan 09-01)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.task import DeadlineType, Task, TaskPriority
from app.schemas.task import TaskCreateRequest, TaskCreateResponse, TaskUpdateRequest


def test_deadline_type_enum_values() -> None:
    assert DeadlineType.SOFT.value == "soft"
    assert DeadlineType.HARD.value == "hard"


def test_task_model_has_deadline_type_column() -> None:
    cols = {c.name for c in Task.__table__.columns}
    assert "deadline_type" in cols
    assert Task.__table__.c.deadline_type.nullable is True


def test_task_model_has_estimated_effort_minutes_column() -> None:
    cols = {c.name for c in Task.__table__.columns}
    assert "estimated_effort_minutes" in cols
    assert Task.__table__.c.estimated_effort_minutes.nullable is True


def test_create_request_accepts_estimated_effort_minutes() -> None:
    assert TaskCreateRequest(title="x").estimated_effort_minutes is None
    assert TaskCreateRequest(title="x", estimated_effort_minutes=60).estimated_effort_minutes == 60
    with pytest.raises(ValidationError):
        TaskCreateRequest(title="x", estimated_effort_minutes=0)
    with pytest.raises(ValidationError):
        TaskCreateRequest(title="x", estimated_effort_minutes=10081)


def test_update_request_accepts_deadline_type() -> None:
    assert TaskUpdateRequest().deadline_type is None
    assert TaskUpdateRequest(deadline_type=DeadlineType.SOFT).deadline_type == DeadlineType.SOFT
    with pytest.raises(ValidationError):
        TaskUpdateRequest(deadline_type="urgent")


def test_create_response_new_fields_default_none() -> None:
    response = TaskCreateResponse(
        id=1,
        title="t",
        priority=TaskPriority.MEDIUM,
        user_id=1,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert response.proposed_deadline is None
    assert response.deadline_type is None
