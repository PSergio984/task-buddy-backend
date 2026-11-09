"""Request/response schemas for the import extraction endpoint."""

from typing import Optional

from pydantic import BaseModel, Field

from app.knowledge.import_extract import ImportTaskProposal


class ImportExtractRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000)


class ImportExtractResponse(BaseModel):
    proposals: list[ImportTaskProposal] = Field(default_factory=list)
    reason: Optional[str] = None
