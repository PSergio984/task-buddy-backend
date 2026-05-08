import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import config

logger = logging.getLogger(__name__)

def get_async_database_url(url: str) -> str:
    """
    Ensures the database URL uses an async driver.
    """
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://")
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
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
