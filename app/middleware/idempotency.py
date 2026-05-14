import json
import logging
import uuid
from typing import Callable

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
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method not in ["POST", "PUT", "PATCH", "DELETE"]:
            return await call_next(request)

        idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not idempotency_key:
            return await call_next(request)

        try:
            uuid.UUID(idempotency_key)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid X-Idempotency-Key format. Must be UUID."}
            )

        user_id = self._get_user_id(request)
        redis_client = get_redis_client()
        if not redis_client:
            return await call_next(request)

        cache_key = f"{CACHE_PREFIX}{user_id}:{idempotency_key}"
        cached_response = await self._get_cached_response(redis_client, cache_key, idempotency_key, user_id)
        if cached_response:
            return cached_response

        await self._set_lock(redis_client, cache_key)

        try:
            response = await call_next(request)
            return await self._handle_response(redis_client, cache_key, response)
        except Exception as e:
            await redis_client.delete(cache_key)
            raise e

    def _get_user_id(self, request: Request) -> str:
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

    async def _get_cached_response(self, redis_client, cache_key, idempotency_key, user_id):
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
        except Exception as e:
            logger.error("Error checking idempotency cache: %s", e)
            return None

    async def _set_lock(self, redis_client, cache_key):
        try:
            await redis_client.set(cache_key, json.dumps("IN_PROGRESS"), ex=30)
        except Exception as e:
            logger.error("Error setting idempotency lock: %s", e)

    async def _handle_response(self, redis_client, cache_key, response):
        if response.status_code >= 500:
            await redis_client.delete(cache_key)
            return response

        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

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

        await redis_client.set(cache_key, json.dumps(cache_payload), ex=TTL)
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type
        )
