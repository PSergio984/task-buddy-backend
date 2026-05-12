from logging.config import fileConfig
from typing import cast

from sqlalchemy import engine_from_config, pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

import os  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import config as app_config  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402, F401
from app.models.base import Base  # noqa: E402
from app.models.notification import Notification, PushSubscription  # noqa: E402, F401
from app.models.project import Project  # noqa: E402, F401
from app.models.tag import Tag  # noqa: E402, F401
from app.models.task import SubTask, Task  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata
if app_config.DATABASE_URL is None:
    raise ValueError("DATABASE_URL is not set in the configuration.")
config.set_main_option(
    "sqlalchemy.url", cast(str, app_config.DATABASE_URL).replace("%", "%%")
)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
