"""Request/response schemas for the breakdown endpoint."""

from typing import Optional

from pydantic import BaseModel, Field

from app.knowledge.breakdown import BreakdownTaskProposal


class BreakdownRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000)
    context_task_id: Optional[int] = None
    # Refine loop: the title of the draft card being regenerated. The client
    # re-sends the original text so the model sees full context plus focus.
    focus_task_title: Optional[str] = Field(None, max_length=200)


class BreakdownResponse(BaseModel):
    tasks: list[BreakdownTaskProposal] = Field(default_factory=list)
    reason: Optional[str] = None
