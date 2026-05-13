import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.notification import PushSubscription


async def check_subs():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(PushSubscription))
        subs = res.scalars().all()
        print(f"Total subscriptions in DB: {len(subs)}")
        for sub in subs:
            print(f"  User {sub.user_id}: {sub.endpoint[:50]}...")

if __name__ == "__main__":
    asyncio.run(check_subs())
