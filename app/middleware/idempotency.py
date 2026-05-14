import json
import logging
from typing import Any, Callable, Optional

from fastapi import Request, Response
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import ALGORITHM, SECRET_KEY
from app.security import get_redis_client

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "X-Idempotency-Key"
CACHE_PREFIX = "idempotency:"
TTL = 3600  # 1 hour

class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle request idempotency using an X-Idempotency-Key header.
    Ensures that identical requests from the same user are not processed multiple times.
    Responses are cached in Redis for a configurable duration.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Intercepts requests to check for idempotency keys and manage response caching.
        Only POST, PUT, PATCH, and DELETE requests are subject to idempotency checks.
        """
        if request.method not in ["POST", "PUT", "PATCH", "DELETE"]:
            return await call_next(request)

        idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not idempotency_key:
            return await call_next(request)

        # Basic length validation to prevent abuse
        if len(idempotency_key) < 8:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid X-Idempotency-Key format. Must be at least 8 characters."}
            )

        user_id = self._get_user_id(request)
        redis_client = get_redis_client()
        if not redis_client:
            # Fail open if Redis is unavailable to avoid blocking all mutations
            return await call_next(request)

        cache_key = f"{CACHE_PREFIX}{user_id}:{idempotency_key}"

        # 1. Check if we have a cached response or an in-progress lock
        cached_response = await self._get_cached_response(redis_client, cache_key, idempotency_key, user_id)
        if cached_response:
            return cached_response

        # 2. Try to acquire an atomic lock
        if not await self._set_lock(redis_client, cache_key):
            # If lock acquisition fails, check again if it finished in the meantime
            cached_response = await self._get_cached_response(redis_client, cache_key, idempotency_key, user_id)
            if cached_response:
                return cached_response

            # Otherwise, return conflict as it's truly in progress
            return JSONResponse(
                status_code=409,
                content={"detail": "Request already in progress with this idempotency key."}
            )

        try:
            # 3. Process the request
            response = await call_next(request)
            return await self._handle_response(redis_client, cache_key, response)
        except Exception as e:
            # 4. Clean up lock on failure so user can retry
            await redis_client.delete(cache_key)
            raise e

    def _get_user_id(self, request: Request) -> str:
        """
        Extract user ID from JWT token in Authorization header or cookies.
        Defaults to 'anonymous' if no token is found.
        """
        auth_header = request.headers.get("Authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        else:
            token = request.cookies.get("access_token")

        if token:
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                return payload.get("sub", "anonymous")
            except JWTError:
                pass
        return "anonymous"

    async def _get_cached_response(self, redis_client: Any, cache_key: str, idempotency_key: str, user_id: str) -> Optional[Response]:
        """
        Retrieve a cached response from Redis if it exists.
        Returns a JSONResponse(409) if the request is still in progress.
        """
        try:
            cached_data = await redis_client.get(cache_key)
            if not cached_data:
                return None

            data = json.loads(cached_data)
            if data == "IN_PROGRESS":
                return JSONResponse(
                    status_code=409,
                    content={"detail": "Request already in progress with this idempotency key."}
                )

            logger.info("Returning cached response for idempotency key: %s (user: %s)", idempotency_key, user_id)
            return Response(
                content=data["body"],
                status_code=data["status_code"],
                headers=data["headers"],
                media_type=data["media_type"]
            )
        except Exception:
            logger.exception("Error checking idempotency cache")
            return None

    async def _set_lock(self, redis_client: Any, cache_key: str) -> bool:
        """
        Set an atomic lock in Redis to indicate a request is in progress.
        Uses SET NX to ensure only one request can acquire the lock.
        """
        try:
            # nx=True makes the set atomic: only succeeds if key doesn't exist
            success = await redis_client.set(cache_key, json.dumps("IN_PROGRESS"), ex=30, nx=True)
            return bool(success)
        except Exception:
            logger.exception("Error setting idempotency lock")
            # If we can't set a lock, we shouldn't proceed to avoid double processing
            return False

    async def _handle_response(self, redis_client: Any, cache_key: str, response: Response) -> Response:
        """
        Finalize the response handling: cache successful responses and clean up locks for errors.
        """
        # Don't cache server errors or rate limit responses
        if response.status_code >= 500 or response.status_code == 429:
            await redis_client.delete(cache_key)
            return response

        # Consume the response body to cache it
        if hasattr(response, "body_iterator"):
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk
        else:
            response_body = response.body

        # Ensure response_body is always bytes (Starlette can return memoryview)
        response_body = bytes(response_body or b"")

        try:
            body_str = response_body.decode("utf-8")
        except UnicodeDecodeError:
            body_str = response_body.hex()

        cache_payload = {
            "status_code": response.status_code,
            "body": body_str,
            "headers": dict(response.headers),
            "media_type": response.media_type
        }

        # Store the full response in cache
        await redis_client.set(cache_key, json.dumps(cache_payload), ex=TTL)

        # Return a new response object as the original body_iterator is consumed
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type
        )
