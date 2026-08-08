import asyncio
import datetime
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from jose import jwt

from app.config import config
from app.libs.broadcaster import broadcaster
from app.limiter import limiter
from app.models.user import User
from app.security import get_confirmed_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/realtime",
    tags=["realtime"],
)


@router.post("/token")
@limiter.limit(config.RATE_LIMIT_REALTIME_TOKEN)
async def realtime_token(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
) -> dict:
    """
    Mint a short-lived Supabase JWT for Realtime subscriptions.

    The frontend calls this before subscribing and refreshes on expiry
    (supabase.realtime.setAuth). Signed with the project's imported ES256
    signing key (JWK on disk); claims: role=authenticated, sub=<user_id>, exp.
    """
    try:
        signing_key = request.app.state.signing_key_cache.load(
            config.SUPABASE_SIGNING_KEY_FILE
        )
    except ValueError as e:
        logger.warning("Realtime token minting unavailable: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Realtime token minting unavailable",
        ) from e

    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=config.SUPABASE_REALTIME_TOKEN_EXPIRE_SECONDS
    )
    payload = {
        "role": "authenticated",
        "sub": str(current_user.id),
        "exp": expire,
    }
    token = jwt.encode(
        payload,
        signing_key.private_key,
        algorithm="ES256",
        headers={"kid": signing_key.kid},
    )
    logger.info("Minted realtime token (kid=%s)", signing_key.kid)
    return {
        "token": token,
        "expires_in": config.SUPABASE_REALTIME_TOKEN_EXPIRE_SECONDS,
    }


@router.get("/stream")
async def stream(
    request: Request,
    current_user: Annotated[User, Depends(get_confirmed_user)],
):
    """
    SSE endpoint for real-time updates.
    """
    async def event_generator():
        queue = broadcaster.subscribe(current_user.id)
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
            broadcaster.unsubscribe(current_user.id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
