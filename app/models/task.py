from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from pydantic import ConfigDict


class TaskCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None


class TaskCreateResponse(TaskCreateRequest):
    id: int
    created_at: datetime


class SubTaskCreateRequest(BaseModel):
    task_id: int
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None


class SubTaskCreateResponse(SubTaskCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class TaskWithSubTasks(BaseModel):
    task: TaskCreateResponse
    subtasks: list[SubTaskCreateResponse]
