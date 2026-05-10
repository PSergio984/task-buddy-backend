from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import TaskPriority
from app.schemas.tag import TagResponse


class SubTaskCreateNestedRequest(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: bool = False


class TaskCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: bool = False
    priority: TaskPriority = TaskPriority.MEDIUM
    project_id: Optional[int] = None
    tags: list[str] = Field(default_factory=list)
    subtasks: list[SubTaskCreateNestedRequest] = Field(default_factory=list)


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


class TaskCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: bool = False
    priority: TaskPriority
    project_id: Optional[int] = None
    user_id: int
    created_at: datetime
    tags: list[TagResponse] = Field(default_factory=list)
    subtasks: list[SubTaskCreateResponse] = Field(default_factory=list)


TaskCreateResponse.model_rebuild()


class TaskWithSubTasks(BaseModel):
    task: TaskCreateResponse
    subtasks: list[SubTaskCreateResponse]


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None
    priority: Optional[TaskPriority] = None
    project_id: Optional[int] = None
    tags: Optional[list[str]] = None


class SubTaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None
