import logging
from typing import Any, Optional, TypeVar

from pydantic import TypeAdapter

from app.security import get_redis_client

logger = logging.getLogger(__name__)

T = TypeVar("T")

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
    except Exception:
        logger.exception("Error storing in cache")

def get_cache_key(prefix: str, user_id: int, **params) -> str:
    """
    Generate a stable cache key.
    """
    sorted_params = sorted(params.items())
    params_str = ":".join(f"{k}={v}" for k, v in sorted_params if v is not None)
    return f"cache:{prefix}:{user_id}:{params_str}"
