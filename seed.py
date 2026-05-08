import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.tag import Tag
from app.models.task import SubTask, Task
from app.models.user import User
from app.security import get_password_hash


async def seed_data():
    async with AsyncSessionLocal() as session:
        try:
            # 1. Create a confirmed user
            email = "seeduser@example.com"
            username = "seeduser"
            password = "seedpassword123"

            # Check if user already exists
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            existing_user = result.scalar_one_or_none()

            if existing_user:
                # Check tasks
                stmt = select(Task).where(Task.user_id == existing_user.id)
                result = await session.execute(stmt)
                tasks = result.scalars().all()
                if len(tasks) >= 2:
                    print(f"User {email} and tasks already exist. Skipping seed.")
                    return
                else:
                    print(f"User {email} exists but missing tasks. Recreating...")
                    await session.delete(existing_user)
                    await session.commit()

            print(f"Creating user {email}...")
            new_user = User(
                username=username,
                email=email,
                password=get_password_hash(password),
                confirmed=True,
                confirmation_failed=False,
            )
            session.add(new_user)
            await session.flush()  # Get ID

            # 2. Create Tags
            tag_names = ["Work", "Personal", "Urgent", "Shopping"]
            tags = []
            for name in tag_names:
                tag = Tag(user_id=new_user.id, name=name)
                session.add(tag)
                tags.append(tag)
            await session.flush()
            tag_map = {t.name: t for t in tags}

            # 3. Create Tasks
            now = datetime.now()

            task1 = Task(
                user_id=new_user.id,
                title="Complete Project Presentation",
                description="Finish the slide deck for tomorrow's meeting",
                due_date=now + timedelta(days=1),
                completed=False,
            )
            session.add(task1)
            await session.flush()

            # Link tags
            from app.models.task import task_tags

            await session.execute(
                task_tags.insert().values(
                    [
                        {"task_id": task1.id, "tag_id": tag_map["Work"].id},
                        {"task_id": task1.id, "tag_id": tag_map["Urgent"].id},
                    ]
                )
            )

            # Subtasks
            subtasks1 = [
                SubTask(
                    user_id=new_user.id, task_id=task1.id, title="Create outline", completed=True
                ),
                SubTask(
                    user_id=new_user.id, task_id=task1.id, title="Draft slides", completed=False
                ),
                SubTask(
                    user_id=new_user.id, task_id=task1.id, title="Review with team", completed=False
                ),
            ]
            session.add_all(subtasks1)

            # Task 2
            task2 = Task(
                user_id=new_user.id,
                title="Weekly Groceries",
                description="Get food for the week",
                due_date=now + timedelta(days=2),
                completed=False,
            )
            session.add(task2)
            await session.flush()

            # Link tags
            await session.execute(
                task_tags.insert().values(
                    [
                        {"task_id": task2.id, "tag_id": tag_map["Personal"].id},
                        {"task_id": task2.id, "tag_id": tag_map["Shopping"].id},
                    ]
                )
            )

            # Subtasks
            subtasks2 = [
                SubTask(
                    user_id=new_user.id, task_id=task2.id, title="Milk & Eggs", completed=False
                ),
                SubTask(user_id=new_user.id, task_id=task2.id, title="Vegetables", completed=False),
            ]
            session.add_all(subtasks2)

            await session.commit()
            print("Database seeding completed successfully.")
        except Exception as e:
            await session.rollback()
            print(f"Error during seeding: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(seed_data())
