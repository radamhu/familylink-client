"""Async SQLAlchemy session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from familylink_server.config import settings

_engine = create_async_engine(settings.database_url, echo=False)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session.

    Yields an AsyncSession from the configured engine. Use as:
        async with get_session() as session:
            # use session

    """
    async with _session_factory() as session:
        yield session
