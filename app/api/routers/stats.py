import sqlalchemy
from typing import Annotated
from fastapi import APIRouter, Depends
from app.database import database, tbl_task, tbl_tag, tbl_task_tags
from app.security import get_current_user
from app.models.stats import SystemOverview, TaskStats, TagDistribution

router = APIRouter(prefix="/stats", tags=["stats"])

@router.get("/overview", response_model=SystemOverview)
async def get_system_overview(current_user: Annotated[dict, Depends(get_current_user)]):
    """
    Retrieve a summary of tasks and tag distribution for the current user.
    """
    # Task Stats
    query_total = sqlalchemy.select(sqlalchemy.func.count()).select_from(tbl_task).where(tbl_task.c.user_id == current_user["id"])
    query_completed = sqlalchemy.select(sqlalchemy.func.count()).select_from(tbl_task).where(
        (tbl_task.c.user_id == current_user["id"]) & (tbl_task.c.completed == True)
    )
    
    total_tasks = await database.fetch_val(query_total) or 0
    completed_tasks = await database.fetch_val(query_completed) or 0
    pending_tasks = total_tasks - completed_tasks
    completion_percentage = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
    
    task_stats = TaskStats(
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        completion_percentage=round(completion_percentage, 2)
    )
    
    # Tag Distribution
    # We join tbl_task_tags with tbl_tag to get names and counts
    query_tags = (
        sqlalchemy.select(tbl_tag.c.name, sqlalchemy.func.count(tbl_task_tags.c.task_id).label("task_count"))
        .select_from(tbl_tag.join(tbl_task_tags, tbl_tag.c.id == tbl_task_tags.c.tag_id))
        .where(tbl_tag.c.user_id == current_user["id"])
        .group_by(tbl_tag.c.name)
    )
    
    tag_results = await database.fetch_all(query_tags)
    tag_distribution = [TagDistribution(tag_name=row["name"], task_count=row["task_count"]) for row in tag_results]
    
    return SystemOverview(
        task_stats=task_stats,
        tag_distribution=tag_distribution
    )
