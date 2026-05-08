from pydantic import BaseModel, ConfigDict
from datetime import datetime


class TagCreate(BaseModel):
    name: str


class TagResponse(TagCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
