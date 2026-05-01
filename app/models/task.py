from pydantic import BaseModel
from datetime import datetime
from typing import Optional


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
    id: int
    created_at: datetime


class TaskWithSubTasks(BaseModel):
    task: TaskCreateResponse
    subtasks: list[SubTaskCreateResponse]
