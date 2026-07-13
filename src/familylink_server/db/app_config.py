"""Shared AppConfig get-or-create helper."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from familylink_server.db.models import AppConfig

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_or_create_app_config(
    session: AsyncSession, child_id: str, package_name: str
) -> AppConfig:
    """Get the AppConfig row for (child_id, package_name), creating it if absent."""
    stmt = select(AppConfig).where(
        AppConfig.child_id == child_id, AppConfig.package_name == package_name
    )
    config = (await session.execute(stmt)).scalar_one_or_none()
    if config is None:
        config = AppConfig(
            child_id=child_id, app_name=package_name, package_name=package_name
        )
        session.add(config)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            config = (await session.execute(stmt)).scalar_one()
    return config
