from fastapi import Request
from slowapi import Limiter

from app.config import config


def get_real_ip(request: Request) -> str:
    """
    Returns the real client IP for rate limiting.

    Behind a trusted proxy (Render), X-Forwarded-For is client-supplied
    values followed by the proxy-appended peer IP, so the LAST entry is the
    untrusted-client-safe one. Taking the first entry would let a caller
    rotate a spoofed header per request and bypass every limiter (login
    brute-force, LLM spend gates).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
        if entries:
            return entries[-1]
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
