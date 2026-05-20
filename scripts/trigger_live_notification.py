import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.notification import Notification
from app.models.task import Task
from app.models.user import User
from app.tasks import _process_reminders_async


async def main():
    print("Connecting to live development database...")
    async with AsyncSessionLocal() as db:
        # Find the first user in the database
        user_result = await db.execute(select(User).limit(1))
        user = user_result.scalar_one_or_none()

        if not user:
            print("❌ No users found in the database. Please register a user first.")
            return

        print(f"✅ Found user: {user.email} (ID: {user.id})")

        # Create a task due exactly 60 minutes from now
        now = datetime.now(timezone.utc)
        due_in_1_hour = now + timedelta(minutes=60)

        new_task = Task(
            title="Live Test: REMINDER_BEFORE",
            description="This task was created to trigger a 60-minute reminder.",
            due_date=due_in_1_hour,
            completed=False,
            user_id=user.id,
            project_id=None
        )
        db.add(new_task)
        await db.commit()
        await db.refresh(new_task)

        print(f"✅ Created Task ID {new_task.id} due at {due_in_1_hour}")

        # Trigger the reminder processor manually
        print("🔄 Running background reminder processor...")
        await _process_reminders_async()

        # Verify the notification was created
        notif_result = await db.execute(
            select(Notification)
            .where(Notification.task_id == new_task.id)
        )
        notifs = notif_result.scalars().all()

        if notifs:
            print(f"🎉 SUCCESS! {len(notifs)} notification(s) created in the live database.")
            for n in notifs:
                print(f"   -> [{n.type}] {n.title}: {n.message}")
            print("\n👉 Go to your frontend browser! You should see the Notification Bell badge light up within 2 minutes (or refresh the page).")
        else:
            print("❌ Something went wrong, no notifications were created.")

if __name__ == "__main__":
    asyncio.run(main())
