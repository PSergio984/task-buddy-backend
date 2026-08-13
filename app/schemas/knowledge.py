"""Pydantic schemas for task-attached knowledge."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.models.knowledge import SourceType


class KnowledgeCreateRequest(BaseModel):
    source_type: SourceType = SourceType.NOTE
    title: Optional[str] = Field(None, max_length=200)
    content: str = Field(..., min_length=1, max_length=20000)
    # Wire field is "metadata"; "metadata_" is the Python attribute to avoid
    # shadowing concerns. validation_alias also accepts the ORM attribute name
    # so from_attributes responses can map extra_metadata directly.
    metadata_: Optional[dict] = Field(
        default=None,
        validation_alias=AliasChoices("extra_metadata", "metadata"),
        serialization_alias="metadata",
    )

    model_config = ConfigDict(populate_by_name=True)


class KnowledgeUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = Field(None, min_length=1, max_length=20000)
    metadata_: Optional[dict] = Field(
        default=None,
        validation_alias=AliasChoices("extra_metadata", "metadata"),
        serialization_alias="metadata",
    )

    model_config = ConfigDict(populate_by_name=True)


class KnowledgeResponse(KnowledgeCreateRequest):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    user_id: int
    task_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None


class Citation(BaseModel):
    """A retrieved chunk cited in an answer."""

    knowledge_id: int
    chunk_text: str
    rrf_score: float


class KnowledgeAskRequest(BaseModel):
    """Query for the assistant. None means 'use the task title'."""

    query: Optional[str] = Field(None, min_length=1, max_length=500)


class KnowledgeAskResponse(BaseModel):
    """Generated answer + per-call metrics + judge verdict.

    Deliberately contains no field that could hold an API key (T-7-13).
    """

    task_id: int
    answer: str
    citations: list[Citation]
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    response_time_ms: float
    judge_verdict: Optional[str]
    judge_explanation: Optional[str]
    answer_id: int


class FeedbackCreateRequest(BaseModel):
    """User +1/-1 on an answer."""

    rating: Literal[1, -1]
    comment: Optional[str] = Field(None, max_length=1000)


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    answer_id: int
    rating: int
    comment: Optional[str]
    created_at: datetime
