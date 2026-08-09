from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: Optional[str] = None
    icon: Optional[str] = None
    position: int = 0


class TagResponse(TagCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime


class TagUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    color: Optional[str] = None
    icon: Optional[str] = None
    position: Optional[int] = None
