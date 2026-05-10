from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None
    icon: Optional[str] = None


class TagResponse(TagCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
