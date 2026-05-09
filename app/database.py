import logging
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import config

logger = logging.getLogger(__name__)


def _handle_sqlite(url: str) -> tuple[str, dict]:
    """Applies async driver and thread safety settings for SQLite."""
    if "aiosqlite" not in url:
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url, {"check_same_thread": False}


def _sanitize_pg_params(query: dict[str, list[str]]) -> dict:
    """Extracts and sanitizes PostgreSQL connection arguments."""
    c_args = {}
    
    # Precedence: sslmode handled first, then 'ssl' if not already set by sslmode
    if "sslmode" in query:
        ssl_value = query.pop("sslmode")[0]
        if ssl_value in ["require", "prefer", "allow", "verify-ca", "verify-full"]:
            c_args["ssl"] = True
        elif ssl_value == "disable":
            c_args["ssl"] = False

    if "ssl" in query:
        ssl_val = query.pop("ssl")[0].lower()
        if "ssl" not in c_args:
            c_args["ssl"] = ssl_val == "true"

    # Remove other unsupported libpq parameters
    for param in ["channel_binding", "gssencmode", "target_session_attrs"]:
        if param in query:
            query.pop(param)
            
    return c_args


def _handle_postgresql(url: str) -> tuple[str, dict]:
    """Applies async driver and sanitizes query parameters for PostgreSQL."""
    if "asyncpg" not in url:
        scheme = "postgres://" if url.startswith("postgres://") else "postgresql://"
        url = url.replace(scheme, "postgresql+asyncpg://", 1)

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    c_args = _sanitize_pg_params(query)

    new_query = urlencode(query, doseq=True)
    sanitized_url = urlunparse(parsed._replace(query=new_query))
    return sanitized_url, c_args


def get_async_database_url(url: str | None) -> tuple[str, dict]:
    """
    Ensures the database URL uses an async driver and handles driver-specific query parameters.
    Returns a tuple of (sanitized_url, connect_args).
    """
    if not url:
        return "", {}

    if url.startswith("sqlite"):
        return _handle_sqlite(url)

    if "postgresql" in url or "postgres" in url:
        return _handle_postgresql(url)

    return url, {}


# Get the async-compatible URL and connection arguments
ASYNC_DATABASE_URL, connect_args = get_async_database_url(config.DATABASE_URL)

# Create the async engine
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    connect_args=connect_args,
    echo=config.DEBUG,
)

# Create the session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base metadata is now managed by individual models inheriting from app.models.base.Base
