import asyncio
from collections import defaultdict


class Broadcaster:
    def __init__(self):
        self.subscribers = defaultdict(set)

    def subscribe(self, user_id: int):
        queue = asyncio.Queue()
        self.subscribers[user_id].add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue):
        if queue in self.subscribers[user_id]:
            self.subscribers[user_id].remove(queue)
        if not self.subscribers[user_id]:
            del self.subscribers[user_id]

    async def notify(self, user_id: int, event: str):
        if user_id in self.subscribers:
            for queue in self.subscribers[user_id]:
                await queue.put(event)

broadcaster = Broadcaster()
