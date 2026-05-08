import logging
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import config

logger = logging.getLogger(__name__)


def get_async_database_url(url: str | None) -> tuple[str, dict]:
    """
    Ensures the database URL uses an async driver and handles driver-specific query parameters.
    Returns a tuple of (sanitized_url, connect_args).
    """
    if not url:
        return "", {}

    c_args = {}
    if url.startswith("sqlite://"):
        if "aiosqlite" not in url:
            url = url.replace("sqlite://", "sqlite+aiosqlite://")
        c_args["check_same_thread"] = False
        return url, c_args

    # Handle postgresql and postgres schemes
    if "postgresql" in url or "postgres" in url:
        # Ensure the async driver is used
        if "asyncpg" not in url:
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            else:
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        # Handle libpq parameters for asyncpg compatibility
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        # asyncpg compatibility: move sslmode to connect_args as 'ssl'
        if "sslmode" in query:
            ssl_value = query.pop("sslmode")[0]
            if ssl_value in ["require", "prefer", "allow", "verify-ca", "verify-full"]:
                c_args["ssl"] = True
            elif ssl_value == "disable":
                c_args["ssl"] = False

        # Strip other unsupported libpq parameters
        for param in ["channel_binding", "gssencmode", "target_session_attrs", "ssl"]:
            if param in query:
                # If 'ssl' is in query, use it for c_args if not already set
                if param == "ssl" and "ssl" not in c_args:
                    val = query[param][0].lower()
                    c_args["ssl"] = val == "true"
                query.pop(param)

        new_query = urlencode(query, doseq=True)
        sanitized_url = urlunparse(parsed._replace(query=new_query))
        return sanitized_url, c_args

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
