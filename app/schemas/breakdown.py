"""Request/response schemas for the breakdown endpoint."""

from typing import Optional

from pydantic import BaseModel, Field

from app.knowledge.breakdown import BreakdownTaskProposal


class BreakdownRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000)
    context_task_id: Optional[int] = None
    # Refine loop: the stable chip number of the draft card being regenerated
    # (replacement is keyed on this), plus its current title as prompt context.
    focus_task_number: Optional[int] = Field(None, ge=1)
    focus_task_title: Optional[str] = Field(None, max_length=200)


class BreakdownResponse(BaseModel):
    tasks: list[BreakdownTaskProposal] = Field(default_factory=list)
    reason: Optional[str] = None
