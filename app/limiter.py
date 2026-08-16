import logging
import urllib.parse

from fastapi import Request
from slowapi import Limiter

from app.config import config

logger = logging.getLogger(__name__)

# If RATE_LIMIT_STORAGE=redis is ever enabled (multi-instance), the storage's
# pool must stay well under Redis Cloud's ~30-client cap — the app's own
# client (cache/blacklist/idempotency) is separately bounded at 15.
REDIS_LIMITER_POOL_MAX_CONNECTIONS = 10


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


def redact_url(url: str) -> str:
    """Strip credentials from a redis:// URL for logging (never leak secrets)."""
    parsed = urllib.parse.urlsplit(url)
    if not parsed.password:
        return url
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    netloc = f"{parsed.username or 'default'}:***@{host}" if parsed.username else host
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def create_limiter() -> Limiter:
    """
    Factory function to create and configure a slowapi Limiter instance.

    Default storage is in-memory: Render free tier runs a single instance, so
    Redis-backed limits buy nothing while adding a second unbounded connection
    pool (the "max number of clients reached" incident). Redis storage remains
    available via RATE_LIMIT_STORAGE=redis with a bounded pool.
    """
    storage_uri = "memory://"
    storage_options: dict = {}
    if config.ENV_STATE != "test" and config.RATE_LIMIT_STORAGE == "redis" and config.REDIS_URL:
        storage_uri = config.REDIS_URL
        from redis import ConnectionPool

        storage_options = {
            "connection_pool": ConnectionPool.from_url(
                config.REDIS_URL,
                max_connections=REDIS_LIMITER_POOL_MAX_CONNECTIONS,
            )
        }

    limiter_instance = Limiter(
        key_func=get_real_ip,
        enabled=config.RATE_LIMIT_ENABLED,
        storage_uri=storage_uri,
        storage_options=storage_options,
        headers_enabled=True,
    )
    logger.info(
        "Limiter created: enabled=%s, storage=%s",
        limiter_instance.enabled,
        redact_url(storage_uri),
    )
    return limiter_instance


limiter = create_limiter()
