from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class TaskCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None


class TaskCreateResponse(TaskCreateRequest):
    user_id: int
    id: int
    created_at: datetime


class SubTaskCreateRequest(BaseModel):
    task_id: int
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None


class SubTaskCreateResponse(SubTaskCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    id: int
    created_at: datetime


class TaskWithSubTasks(BaseModel):
    task: TaskCreateResponse
    subtasks: list[SubTaskCreateResponse]
