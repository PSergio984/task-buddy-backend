from fastapi import Request
from slowapi import Limiter

from app.config import config


def get_real_ip(request: Request) -> str:
    """
    Returns the real client IP, respecting X-Forwarded-For if present.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For: client, proxy1, proxy2
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def create_limiter() -> Limiter:
    """
    Factory function to create and configure a slowapi Limiter instance.
    Uses Redis storage in production/dev and memory storage in tests.
    """
    storage_uri = "memory://"
    if config.ENV_STATE != "test" and config.REDIS_URL:
        storage_uri = config.REDIS_URL

    limiter_instance = Limiter(
        key_func=get_real_ip,
        enabled=config.RATE_LIMIT_ENABLED,
        storage_uri=storage_uri,
        headers_enabled=True,
    )
    print(f"Limiter created: enabled={limiter_instance.enabled}, storage={storage_uri}")
    return limiter_instance


limiter = create_limiter()
