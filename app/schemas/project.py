from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ProjectBase(BaseModel):
    name: str
    color: Optional[str] = None
    icon: Optional[str] = None
    position: int = 0


class ProjectCreateRequest(ProjectBase):
    pass


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    position: Optional[int] = None


class ProjectResponse(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
