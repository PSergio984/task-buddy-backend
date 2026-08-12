"""Pydantic schemas for task-attached knowledge."""

from datetime import datetime
from typing import Optional

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
