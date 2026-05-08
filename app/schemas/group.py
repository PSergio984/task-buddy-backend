from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class GroupBase(BaseModel):
    name: str
    color: Optional[str] = None


class GroupCreateRequest(GroupBase):
    pass


class GroupUpdateRequest(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class GroupResponse(GroupBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
