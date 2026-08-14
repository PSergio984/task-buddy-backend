"""Rule-based soft-deadline proposal — pure, no I/O, no LLM (D-05)."""

import math
from datetime import datetime, timedelta, timezone

from app.models.task import TaskPriority

PROPOSAL_BASE_DAYS: dict[TaskPriority, int] = {
    TaskPriority.HIGH: 2,
    TaskPriority.MEDIUM: 4,
    TaskPriority.LOW: 7,
}
PROPOSAL_EFFORT_DAY_DIVISOR: int = 480  # one extra day per full 8h of estimate
MAX_PROPOSAL_DAYS: int = 14


def propose_deadline(
    priority: TaskPriority,
    estimated_effort_minutes: int | None = None,
    *,
    now: datetime | None = None,
) -> datetime:
    """Propose a soft deadline: priority base days + effort bump, capped.

    Pure and deterministic via the ``now`` injection point; the default keeps
    the caller side clean.
    """
    days = PROPOSAL_BASE_DAYS[priority]
    if estimated_effort_minutes is not None:
        days += math.ceil(estimated_effort_minutes / PROPOSAL_EFFORT_DAY_DIVISOR)
    days = min(days, MAX_PROPOSAL_DAYS)
    base = now if now is not None else datetime.now(timezone.utc)
    return base + timedelta(days=days)
