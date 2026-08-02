"""Background asyncio task that force-blocks apps Google fails to enforce daily limits on."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from familylink_server.db.models import AppConfig, AuditLog
from familylink_server.db.session import make_session

if TYPE_CHECKING:
    from familylink.models import AppUsage
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

logger = logging.getLogger(__name__)

POLL_INTERVAL = 300


def _usage_minutes_by_package(usage: AppUsage, today: date) -> dict[str, float]:
    """Sum today's per-package usage, in minutes, from raw usage sessions."""
    totals: dict[str, float] = {}
    for session in usage.app_usage_sessions:
        if (session.date.year, session.date.month, session.date.day) != (
            today.year,
            today.month,
            today.day,
        ):
            continue
        package = session.app_id.android_app_package_name
        totals[package] = totals.get(package, 0.0) + float(session.usage) / 60
    return totals


async def enforce_child(
    child_id: str,
    svc: FamilyLinkService,
    notifier: DiscordNotifier | None = None,
) -> None:
    """Block/restore one child's opted-in apps based on live Google usage vs. limit."""
    today = date.today()
    async with make_session() as session:
        result = await session.execute(
            select(AppConfig).where(
                AppConfig.child_id == child_id,
                AppConfig.auto_block_enabled.is_(True),
            )
        )
        configs = result.scalars().all()
        if not configs:
            return

        usage = await svc.get_apps_and_usage(child_id, bypass_cache=True)
        usage_by_package = _usage_minutes_by_package(usage, today)
        apps_by_package = {a.package_name: a for a in usage.apps}

        for config in configs:
            app = apps_by_package.get(config.package_name)
            live_limit = (
                app.supervision_setting.usage_limit.daily_usage_limit_mins
                if app is not None and app.supervision_setting.usage_limit is not None
                else None
            )

            if (
                config.auto_blocked_at is not None
                and config.auto_blocked_at.date() < today
            ):
                restore_limit = (
                    config.max_mins if config.max_mins is not None else live_limit
                )
                if restore_limit is None:
                    continue
                await svc.set_app_limit(config.package_name, restore_limit, child_id)
                config.auto_blocked_at = None
                session.add(
                    AuditLog(
                        child_id=child_id,
                        action='auto_unblock',
                        target=config.package_name,
                        new_value=f'{restore_limit} min',
                        occurred_at=datetime.now(UTC),
                    )
                )
                if notifier:
                    await notifier.notify_change(
                        'auto_unblock', child_id, config.package_name, 'enforcer'
                    )
                continue

            if app is None or live_limit is None:
                continue
            limit_mins = live_limit

            bonus = config.bonus_mins if config.bonus_date == today else 0
            effective_limit = limit_mins + bonus
            usage_mins = usage_by_package.get(config.package_name, 0.0)

            if (
                usage_mins >= effective_limit
                and config.auto_blocked_at is None
                and not app.supervision_setting.hidden
            ):
                await svc.block_app(config.package_name, child_id)
                config.auto_blocked_at = datetime.now(UTC)
                config.max_mins = limit_mins
                session.add(
                    AuditLog(
                        child_id=child_id,
                        action='auto_block',
                        target=config.package_name,
                        new_value=f'{usage_mins:.0f}/{effective_limit} min',
                        occurred_at=datetime.now(UTC),
                    )
                )
                if notifier:
                    await notifier.notify_change(
                        'auto_block', child_id, config.package_name, 'enforcer'
                    )

        await session.commit()


async def app_enforcer_loop(
    svc: FamilyLinkService, notifier: DiscordNotifier | None = None
) -> None:
    """Iterate every child with at least one auto-block-enabled app, every POLL_INTERVAL."""
    while True:
        try:
            async with make_session() as session:
                result = await session.execute(
                    select(AppConfig.child_id)
                    .where(AppConfig.auto_block_enabled.is_(True))
                    .distinct()
                )
                child_ids = result.scalars().all()

            results = await asyncio.gather(
                *[
                    enforce_child(child_id, svc, notifier=notifier)
                    for child_id in child_ids
                ],
                return_exceptions=True,
            )
            for child_id, outcome in zip(child_ids, results, strict=True):
                if isinstance(outcome, Exception):
                    logger.exception(
                        'enforce_child failed for child %s', child_id, exc_info=outcome
                    )
        except Exception:
            logger.exception('App enforcer cycle failed')
        await asyncio.sleep(POLL_INTERVAL)
