import logging
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import config

logger = logging.getLogger(__name__)


def get_async_database_url(url: str | None) -> str:
    """
    Ensures the database URL uses an async driver and handles driver-specific query parameters.
    """
    if not url:
        return ""

    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://")

    if url.startswith("postgresql://") or url.startswith("postgres://"):
        # Replace scheme
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        else:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        # Handle sslmode for asyncpg
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        if "sslmode" in query:
            # asyncpg uses 'ssl' instead of 'sslmode'
            ssl_value = query.pop("sslmode")[0]
            if "ssl" not in query:
                # Map sslmode=require to ssl=true for asyncpg compatibility
                if ssl_value in ["require", "prefer", "allow"]:
                    query["ssl"] = ["true"]
                else:
                    query["ssl"] = [ssl_value]

        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    return url


# Get the async-compatible URL
ASYNC_DATABASE_URL = get_async_database_url(config.DATABASE_URL)

# Configure engine arguments
connect_args = {}
if ASYNC_DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

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
