from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.task import TaskPriority
from app.schemas.tag import TagResponse


class SubTaskCreateNestedRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: bool = False
    position: int = 0


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    due_date: Optional[datetime] = None
    completed: bool = False
    priority: TaskPriority = TaskPriority.MEDIUM
    project_id: Optional[int] = None
    tags: list[str] = Field(default_factory=list)
    subtasks: list[SubTaskCreateNestedRequest] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v):
        for tag in v:
            if len(tag) > 20:
                raise ValueError("Tag length cannot exceed 20 characters")
        return v


class SubTaskCreateRequest(BaseModel):
    task_id: int
    title: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: bool = False
    position: int = 0


class SubTaskCreateResponse(SubTaskCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    id: int
    position: int
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
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None
    priority: Optional[TaskPriority] = None
    project_id: Optional[int] = None
    tags: Optional[list[str]] = None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v):
        if v is not None:
            for tag in v:
                if len(tag) > 20:
                    raise ValueError("Tag length cannot exceed 20 characters")
        return v


class SubTaskUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=80)
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None
    position: Optional[int] = None
