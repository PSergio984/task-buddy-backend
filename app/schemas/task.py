from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class TaskCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: bool = False


class TaskCreateResponse(TaskCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    id: int
    created_at: datetime


class SubTaskCreateRequest(BaseModel):
    task_id: int
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: bool = False


class SubTaskCreateResponse(SubTaskCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    id: int
    created_at: datetime


class TaskWithSubTasks(BaseModel):
    task: TaskCreateResponse
    subtasks: list[SubTaskCreateResponse]


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None


class SubTaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None
