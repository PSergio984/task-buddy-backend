from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import config


def create_limiter() -> Limiter:
    """
    Factory function to create and configure a slowapi Limiter instance.
    Uses Redis storage in production/dev and memory storage in tests.
    """
    storage_uri = "memory://"
    if config.ENV_STATE != "test" and config.REDIS_URL:
        storage_uri = config.REDIS_URL

    return Limiter(
        key_func=get_remote_address,
        enabled=config.RATE_LIMIT_ENABLED,
        storage_uri=storage_uri
    )

limiter = create_limiter()
