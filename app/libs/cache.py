import logging
from typing import Any, Optional, TypeVar

from pydantic import TypeAdapter

from app.security import get_redis_client

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _user_index_key(user_id: int) -> str:
    """Redis SET holding every live cache key of one user (invalidation index)."""
    return f"cache:user:{user_id}:keys"


def _parse_user_id(cache_key: str) -> Optional[int]:
    """Extract the user_id segment from a generated key (``cache:{prefix}:{uid}:...``).

    Keys not produced by ``get_cache_key`` (tests, ad-hoc) have no user
    segment — return None so they are simply not tracked.
    """
    parts = cache_key.split(":")
    if len(parts) >= 3 and parts[0] == "cache":
        try:
            return int(parts[2])
        except ValueError:
            return None
    return None


async def delete_cached_user_keys(user_id: int, *prefixes: str) -> None:
    """Invalidate a user's cached keys by indexed lookup — never a KEYS scan.

    Reads the per-user key SET (O(1)-ish), filters by prefix in-process,
    deletes the matches, and prunes them from the index. Expired keys linger
    in the set as harmless members; the delete is a no-op and they are pruned.
    """
    redis_client = get_redis_client()
    if not redis_client:
        return
    try:
        members = await redis_client.smembers(_user_index_key(user_id))
    except Exception:
        logger.exception("Error reading cache index for user %s", user_id)
        return
    if not members:
        return
    stale = [k for k in members if any(k.startswith(p) for p in prefixes)]
    if not stale:
        return
    try:
        await redis_client.delete(*stale)
        await redis_client.srem(_user_index_key(user_id), *stale)
    except Exception:
        logger.exception("Error invalidating cached keys for user %s", user_id)


async def get_cached_data(cache_key: str, model_type: type[T]) -> Optional[T]:
    """
    Retrieve and deserialize data from Redis.
    """
    redis_client = get_redis_client()
    if not redis_client:
        return None

    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            adapter = TypeAdapter(model_type)
            return adapter.validate_json(cached_data)
    except Exception:
        logger.exception("Error retrieving from cache")
    return None


async def set_cached_data(cache_key: str, data: Any, expire: int = 300) -> None:
    """
    Serialize and store data in Redis.
    """
    redis_client = get_redis_client()
    if not redis_client:
        return

    try:
        # If it's a list of Pydantic models or SQLAlchemy objects, we need to serialize them
        # We can use TypeAdapter to serialize consistently
        from fastapi.encoders import jsonable_encoder

        serializable_data = jsonable_encoder(data)
        adapter = TypeAdapter(Any)
        json_data = adapter.dump_json(serializable_data)
        await redis_client.setex(cache_key, expire, json_data)
        # Track the key in the user's invalidation index so mutations can
        # drop exactly the right keys without a KEYS pattern scan.
        user_id = _parse_user_id(cache_key)
        if user_id is not None:
            await redis_client.sadd(_user_index_key(user_id), cache_key)
    except Exception:
        logger.exception("Error storing in cache")


def get_cache_key(prefix: str, user_id: int, **params) -> str:
    """
    Generate a stable cache key.
    """
    sorted_params = sorted(params.items())
    params_str = ":".join(f"{k}={v}" for k, v in sorted_params if v is not None)
    return f"cache:{prefix}:{user_id}:{params_str}"
