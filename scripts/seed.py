import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.database import AsyncSessionLocal, engine
from app.models.base import Base
from app.models.user import User
from app.models.group import Group
from app.models.task import Task, SubTask, TaskPriority
from app.models.tag import Tag
from app.security import get_password_hash

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def seed_data():
    logger.info("Starting database seed...")
    
    # We use engine.begin() if we want to run migrations or drop tables, but here we just seed.
    # Assuming tables are already created via migrations.
    
    async with AsyncSessionLocal() as session:
        # Check if dummy user exists
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.email == "demo@example.com"))
        user = result.scalar_one_or_none()
        
        if not user:
            logger.info("Creating demo user...")
            user = User(
                username="demouser",
                email="demo@example.com",
                password=get_password_hash("password123"),
                confirmed=True
            )
            session.add(user)
            await session.flush()
        else:
            logger.info("Demo user already exists.")
            
        # Check and create Groups (Projects)
        result = await session.execute(select(Group).where(Group.user_id == user.id))
        groups = result.scalars().all()
        
        if not groups:
            logger.info("Creating projects (groups)...")
            g1 = Group(name="Work", user_id=user.id, color="#3b82f6")
            g2 = Group(name="Personal", user_id=user.id, color="#10b981")
            g3 = Group(name="Side Hustle", user_id=user.id, color="#8b5cf6")
            session.add_all([g1, g2, g3])
            await session.flush()
            groups = [g1, g2, g3]
        
        # Create some Tasks and Subtasks
        result = await session.execute(select(Task).where(Task.user_id == user.id))
        existing_tasks = result.scalars().all()
        
        if not existing_tasks:
            logger.info("Creating tasks and subtasks...")
            now = datetime.now(timezone.utc)
            
            t1 = Task(
                title="Finish Q3 Report",
                description="Compile financial data for Q3 and create presentation.",
                user_id=user.id,
                group_id=groups[0].id,
                priority=TaskPriority.HIGH,
                due_date=now + timedelta(days=2)
            )
            
            t2 = Task(
                title="Grocery Shopping",
                description="Get milk, eggs, bread, and veggies.",
                user_id=user.id,
                group_id=groups[1].id,
                priority=TaskPriority.MEDIUM,
                due_date=now + timedelta(days=1)
            )
            
            t3 = Task(
                title="Launch MVP",
                description="Deploy the new side project to production.",
                user_id=user.id,
                group_id=groups[2].id,
                priority=TaskPriority.HIGH,
                due_date=now + timedelta(days=7)
            )
            
            session.add_all([t1, t2, t3])
            await session.flush()
            
            # Subtasks for T1
            st1 = SubTask(title="Collect data from accounting", task_id=t1.id, user_id=user.id, completed=True)
            st2 = SubTask(title="Draft slides", task_id=t1.id, user_id=user.id)
            
            # Subtasks for T3
            st3 = SubTask(title="Setup CI/CD pipeline", task_id=t3.id, user_id=user.id, completed=True)
            st4 = SubTask(title="Configure domain", task_id=t3.id, user_id=user.id)
            
            session.add_all([st1, st2, st3, st4])
            
        await session.commit()
        logger.info("Database seeding complete!")

if __name__ == "__main__":
    asyncio.run(seed_data())
