import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.libs.broadcaster import broadcaster
from app.models.user import User
from app.security import get_confirmed_user

router = APIRouter(
    prefix="/realtime",
    tags=["realtime"],
)

@router.get("/stream")
async def stream(
    request: Request,
    current_user: Annotated[User, Depends(get_confirmed_user)],
):
    """
    SSE endpoint for real-time updates.
    """
    async def event_generator():
        queue = await broadcaster.subscribe(current_user.id)
        try:
            # Send an initial heart beat or connection confirmation
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    # Wait for an event with a timeout to check for disconnection
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {event}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield ": ping\n\n"
        except Exception:
            pass
        finally:
            await broadcaster.unsubscribe(current_user.id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
