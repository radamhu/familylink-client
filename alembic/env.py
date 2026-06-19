"""Alembic environment configuration for database migrations.

Supports both online (live database) and offline (SQL generation) migration modes,
with async support for asyncpg-based PostgreSQL connections.
"""

import asyncio
import sys
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from familylink_server.config import settings
from familylink_server.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Detect if we're running autogenerate
is_autogenerate = "revision" in sys.argv and "--autogenerate" in sys.argv


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This generates SQL for applying migrations without a live database connection.
    """
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    This connects to an actual database and applies migrations.
    """
    connectable = create_async_engine(settings.database_url)
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda sync_conn: context.configure(
                connection=sync_conn, target_metadata=target_metadata
            )
        )
        async with connection.begin():
            await connection.run_sync(lambda _: context.run_migrations())
    await connectable.dispose()


# Determine which mode to run in
if is_autogenerate:
    # For autogenerate with SQLAlchemy 2.0 metadata, configure and let alembic handle it
    # The key is that alembic will compare the target_metadata against the database schema
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
elif context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
