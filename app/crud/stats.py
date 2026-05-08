from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.task import Task, task_tags
from app.models.tag import Tag
from app.schemas.stats import SystemOverview, TaskStats, TagDistribution


async def get_system_overview(db: AsyncSession, user_id: int) -> SystemOverview:
    # Task Stats
    total_query = select(func.count()).select_from(Task).where(Task.user_id == user_id)
    completed_query = select(func.count()).select_from(Task).where(
        Task.user_id == user_id, Task.completed == True
    )
    
    total_tasks = (await db.execute(total_query)).scalar() or 0
    completed_tasks = (await db.execute(completed_query)).scalar() or 0
    pending_tasks = total_tasks - completed_tasks
    completion_percentage = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
    
    task_stats = TaskStats(
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        completion_percentage=round(completion_percentage, 2)
    )
    
    # Tag Distribution
    tag_query = (
        select(Tag.name, func.count(task_tags.c.task_id).label("task_count"))
        .join(task_tags, Tag.id == task_tags.c.tag_id)
        .where(Tag.user_id == user_id)
        .group_by(Tag.name)
    )
    
    tag_results = (await db.execute(tag_query)).all()
    tag_distribution = [
        TagDistribution(tag_name=row.name, task_count=row.task_count) 
        for row in tag_results
    ]
    
    return SystemOverview(
        task_stats=task_stats,
        tag_distribution=tag_distribution
    )
