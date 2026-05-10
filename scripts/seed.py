import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.project import Project
from app.models.task import SubTask, Task, TaskPriority, task_tags
from app.models.tag import Tag
from app.security import get_password_hash

logger = logging.getLogger(__name__)


async def seed_data():
    logger.info("Starting database seed with expanded content...")

    async with AsyncSessionLocal() as session:
        # Identify or Create Demo User
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
            logger.info("Demo user identified. Purging existing data for clean seed...")
            # Purge associations first for THIS user only
            user_task_ids = select(Task.id).where(Task.user_id == user.id).scalar_subquery()
            await session.execute(delete(task_tags).where(task_tags.c.task_id.in_(user_task_ids)))

            await session.execute(delete(SubTask).where(SubTask.user_id == user.id))
            await session.execute(delete(Task).where(Task.user_id == user.id))
            await session.execute(delete(Tag).where(Tag.user_id == user.id))
            await session.execute(delete(Project).where(Project.user_id == user.id))
            await session.flush()

        # 1. Create 4 Projects
        logger.info("Creating 4 high-impact Projects...")
        project_data = [
            {"name": "Strategic Ops", "color": "#2563eb"},
            {"name": "Product Design", "color": "#8b5cf6"},
            {"name": "Growth & Marketing", "color": "#10b981"},
            {"name": "Personal Mastery", "color": "#f59e0b"},
        ]
        
        projects = []
        for p in project_data:
            project = Project(name=p["name"], color=p["color"], user_id=user.id)
            session.add(project)
            projects.append(project)
        await session.flush()

        # 2. Create Common Tags
        logger.info("Defining metadata tags...")
        tag_names = ["Critical", "Research", "Review", "Development", "Outreach", "Wellness"]
        tags = []
        for name in tag_names:
            t = Tag(name=name, user_id=user.id)
            session.add(t)
            tags.append(t)
        await session.flush()

        # 3. Generate 24 Tasks
        logger.info("Generating 24 curated strategic tasks...")
        now = datetime.now(timezone.utc)
        
        task_templates = [
            ("Finalize Q3 Infrastructure Audit", "Deep dive into cloud costs and performance bottlenecks.", 0, TaskPriority.HIGH, 2),
            ("Review Q4 Roadmap with Stakeholders", "Alignment session for upcoming features.", 0, TaskPriority.MEDIUM, 5),
            ("Compliance Certification Renewal", "Annual SOC2 compliance documentation review.", 0, TaskPriority.HIGH, 10),
            ("Quarterly Financial Recap", "Prepare charts for the board meeting.", 0, TaskPriority.MEDIUM, 3),
            ("Legacy API Deprecation Plan", "Phase out v1 endpoints safely.", 0, TaskPriority.LOW, 15),
            ("Update Onboarding Documentation", "Refresh the engineering wiki.", 0, TaskPriority.LOW, 7),
            ("UI Brand System Refresh", "Consolidate design tokens for v2.0.", 1, TaskPriority.HIGH, 1),
            ("User Interview Synthesis", "Extract key pain points from the last 10 sessions.", 1, TaskPriority.MEDIUM, 4),
            ("Accessibility Audit - Main Flow", "Ensure WCAG 2.1 compliance on Dashboard.", 1, TaskPriority.HIGH, 6),
            ("High-Fidelity Mobile Mockups", "Finalize layouts for iOS/Android apps.", 1, TaskPriority.MEDIUM, 8),
            ("Prototyping Interaction Hooks", "Implement micro-interactions for sidebar.", 1, TaskPriority.LOW, 2),
            ("Design Critique: Dark Mode", "Gather feedback on new palette.", 1, TaskPriority.LOW, 3),
            ("Launch Early Access Campaign", "Email sequence for top 500 users.", 2, TaskPriority.HIGH, 0),
            ("SEO Content Strategy Audit", "Keyword research for upcoming blog series.", 2, TaskPriority.MEDIUM, 12),
            ("A/B Test Landing Page Hero", "Compare 'Effortless' vs 'Strategic' messaging.", 2, TaskPriority.HIGH, 2),
            ("Affiliate Program Outreach", "Identify 20 key influencers in productivity space.", 2, TaskPriority.MEDIUM, 9),
            ("Social Media Visual Assets", "Graphics for Twitter/LinkedIn launch.", 2, TaskPriority.LOW, 5),
            ("Analyze Conversion Funnel", "Identify drop-off points in registration.", 2, TaskPriority.MEDIUM, 1),
            ("Advanced React Patterns Study", "Deep dive into Server Components and Actions.", 3, TaskPriority.HIGH, 4),
            ("Weekly Retrospective", "Reflect on wins and alignment with core goals.", 3, TaskPriority.MEDIUM, 0),
            ("Curate Professional Portfolio", "Update project case studies.", 3, TaskPriority.MEDIUM, 20),
            ("Daily Deep Work Session", "2 hours of focused output without distractions.", 3, TaskPriority.HIGH, 0),
            ("Read: 'Building a Second Brain'", "Apply PARA method to current notes.", 3, TaskPriority.LOW, 30),
            ("Setup Automated Backup Logic", "Secure local environment data.", 3, TaskPriority.LOW, 10),
        ]

        tasks = []
        for title, desc, p_idx, priority, due_days in task_templates:
            # Assign 0-2 UNIQUE random tags
            num_tags = random.randint(0, 2)
            assigned_tags = random.sample(tags, num_tags)
            
            task = Task(
                title=title,
                description=desc,
                user_id=user.id,
                project_id=projects[p_idx].id,
                priority=priority,
                due_date=now + timedelta(days=due_days) if due_days >= 0 else None,
                completed=random.random() < 0.2,
                tags=assigned_tags
            )
            session.add(task)
            tasks.append(task)
        await session.flush()

        # 4. Add Subtasks
        logger.info("Adding hierarchical subtasks...")
        subtask_data = [
            (tasks[0].id, ["Review AWS billing", "Identify idle EC2 instances", "Draft cost-saving proposal"]),
            (tasks[6].id, ["Audit color palette", "Update typography scale", "Export SVG assets"]),
            (tasks[12].id, ["Draft email templates", "Segment user list", "Configure tracking links"]),
            (tasks[18].id, ["Watch conference talks", "Implement demo project", "Write summary notes"]),
        ]
        
        for t_id, st_titles in subtask_data:
            for title in st_titles:
                st = SubTask(
                    title=title,
                    task_id=t_id,
                    user_id=user.id,
                    completed=random.random() < 0.4
                )
                session.add(st)

        await session.commit()
        logger.info(f"Database seeding complete! Total tasks: {len(tasks)}, Projects: {len(projects)}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_data())
