"""Plan API wire + parse shapes (POST /api/v1/plan)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    """Request body: optional availability override and response cap."""

    available_minutes: Optional[int] = Field(None, ge=0, le=1440)
    limit: Optional[int] = Field(None, ge=1, le=50)


class PlanTaskRow(BaseModel):
    """One planned task within a bucket (D-14 shape)."""

    task_id: int
    reason: str
    effort_minutes: Optional[int] = None


class PlanBucket(BaseModel):
    """One time period of the plan."""

    period: Literal["tonight", "tomorrow", "later"]
    tasks: list[PlanTaskRow] = Field(default_factory=list)


class PlanVerdict(BaseModel):
    """Structured LLM output — the parse schema (RelevanceVerdict pattern)."""

    buckets: list[PlanBucket]


class PlanResponse(BaseModel):
    """The plan response: buckets + reason + plan_id + metrics."""

    buckets: list[PlanBucket] = Field(default_factory=list)
    reason: Optional[str] = None
    plan_id: Optional[int] = None
    # Metric mirrors of KnowledgeAskResponse (no-LLM path keeps zeros).
    model: str = "rule"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    response_time_ms: float = 0.0
    pool_size: int = 0
    available_minutes: int = 0
