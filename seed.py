import asyncio
from datetime import datetime, timedelta

from app.database import database, tbl_user, tbl_task, tbl_subtask, tbl_tag, tbl_task_tags
from app.security import get_password_hash

async def seed_data():
    is_connected = database.is_connected
    if not is_connected:
        await database.connect()
    
    try:
        async with database.transaction():
            # 1. Create a confirmed user
            email = "seeduser@example.com"
            username = "seeduser"
            password = "seedpassword123"
            
            # Check if user already exists
            query = tbl_user.select().where(tbl_user.c.email == email)
            existing_user = await database.fetch_one(query)
            
            if existing_user:
                task_query = tbl_task.select().where(tbl_task.c.user_id == existing_user.id)
                tasks = await database.fetch_all(task_query)
                if len(tasks) >= 2:
                    print(f"User {email} and tasks already exist. Skipping seed.")
                    return
                else:
                    print(f"User {email} exists but missing tasks. Recreating...")
                    await database.execute(tbl_user.delete().where(tbl_user.c.id == existing_user.id))
        
            print(f"Creating user {email}...")
            user_query = tbl_user.insert().values(
                username=username,
                email=email,
                password=get_password_hash(password),
                confirmed=True,
                confirmation_failed=False
            )
            user_id = await database.execute(user_query)
            
            # 2. Create Tags
            tags = ["Work", "Personal", "Urgent", "Shopping"]
            tag_ids = {}
            for tag in tags:
                tag_query = tbl_tag.insert().values(
                    user_id=user_id,
                    name=tag
                )
                tag_id = await database.execute(tag_query)
                tag_ids[tag] = tag_id
                
            # 3. Create Tasks
            now = datetime.now()
            
            task1_query = tbl_task.insert().values(
                user_id=user_id,
                title="Complete Project Presentation",
                description="Finish the slide deck for tomorrow's meeting",
                due_date=now + timedelta(days=1),
                completed=False
            )
            task1_id = await database.execute(task1_query)
            
            # Link tags
            await database.execute(tbl_task_tags.insert().values(task_id=task1_id, tag_id=tag_ids["Work"]))
            await database.execute(tbl_task_tags.insert().values(task_id=task1_id, tag_id=tag_ids["Urgent"]))
            
            # Subtasks
            await database.execute(tbl_subtask.insert().values(
                user_id=user_id, task_id=task1_id, title="Create outline", completed=True
            ))
            await database.execute(tbl_subtask.insert().values(
                user_id=user_id, task_id=task1_id, title="Draft slides", completed=False
            ))
            await database.execute(tbl_subtask.insert().values(
                user_id=user_id, task_id=task1_id, title="Review with team", completed=False
            ))
            
            # Task 2
            task2_query = tbl_task.insert().values(
                user_id=user_id,
                title="Weekly Groceries",
                description="Get food for the week",
                due_date=now + timedelta(days=2),
                completed=False
            )
            task2_id = await database.execute(task2_query)
            
            # Link tags
            await database.execute(tbl_task_tags.insert().values(task_id=task2_id, tag_id=tag_ids["Personal"]))
            await database.execute(tbl_task_tags.insert().values(task_id=task2_id, tag_id=tag_ids["Shopping"]))
            
            # Subtasks
            await database.execute(tbl_subtask.insert().values(
                user_id=user_id, task_id=task2_id, title="Milk & Eggs", completed=False
            ))
            await database.execute(tbl_subtask.insert().values(
                user_id=user_id, task_id=task2_id, title="Vegetables", completed=False
            ))
            
            print("Database seeding completed successfully.")
    except Exception as e:
        print(f"Error during seeding: {e}")
        raise
    
    if not is_connected:
        await database.disconnect()

if __name__ == "__main__":
    asyncio.run(seed_data())
