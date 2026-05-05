from pydantic import BaseModel

class TaskStats(BaseModel):
    total_tasks: int
    completed_tasks: int
    pending_tasks: int
    completion_percentage: float

class TagDistribution(BaseModel):
    tag_name: str
    task_count: int

class SystemOverview(BaseModel):
    task_stats: TaskStats
    tag_distribution: list[TagDistribution]
