from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.task import TaskPriority
from app.schemas.tag import TagResponse


class TaskCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: bool = False
    priority: TaskPriority = TaskPriority.MEDIUM
    group_id: Optional[int] = None
    tags: list[str] = []


class TaskCreateResponse(TaskCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    id: int
    created_at: datetime
    tags: list[TagResponse] = []


TaskCreateResponse.model_rebuild()


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
    priority: Optional[TaskPriority] = None
    group_id: Optional[int] = None
    tags: Optional[list[str]] = None


class SubTaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None
