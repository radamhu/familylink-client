"""Background asyncio task that polls Linux machines and enforces screen-time limits."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot
from familylink_server.db.session import make_session
from familylink_server.services.linux_ssh import (
    check_session,
    lock_session,
    poweroff_machine,
)

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60


async def poll_machine(
    machine: LinuxMachine, notifier: DiscordNotifier | None = None
) -> None:
    """Poll one machine: skip if powered off, accumulate active seconds, enforce limits.

    Args:
        machine: The LinuxMachine ORM instance to poll.
        notifier: Optional Discord notifier; posts on lock/poweroff when provided.
    """
    today = date.today()

    async with make_session() as session:
        stmt = select(LinuxUsageSnapshot).where(
            LinuxUsageSnapshot.machine_id == machine.id,
            LinuxUsageSnapshot.date == today,
        )
        snapshot = (await session.execute(stmt)).scalar_one_or_none()

        if snapshot is None:
            snapshot = LinuxUsageSnapshot(
                machine_id=machine.id,
                date=today,
                active_seconds=0,
                updated_at=datetime.now(UTC),
            )
            session.add(snapshot)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                snapshot = (await session.execute(stmt)).scalar_one()

        try:
            active = await check_session(
                machine.hostname,
                machine.ssh_port,
                machine.ssh_user,
                machine.ssh_private_key,
            )
        except Exception:
            logger.warning("SSH poll failed for %s", machine.friendly_name)
            # Machine went offline while locked (e.g. child held the power button).
            # poweroff_at was never set via the normal enforcement path, so the UI
            # would show "locked" indefinitely. Mark it as powered off here so the
            # status reflects reality. On next successful SSH the poller clears
            # poweroff_at and immediately re-enforces.
            if snapshot.locked_at is not None and snapshot.poweroff_at is None:
                snapshot.poweroff_at = datetime.now(UTC)
                snapshot.updated_at = datetime.now(UTC)
                logger.info(
                    "Machine %s unreachable while locked — marking as powered off",
                    machine.friendly_name,
                )
                await session.commit()
            return

        if snapshot.poweroff_at is not None:
            snapshot.poweroff_at = None
            logger.info(
                "Machine %s back online after poweroff — will re-enforce immediately",
                machine.friendly_name,
            )

        if active:
            snapshot.active_seconds += POLL_INTERVAL
            snapshot.updated_at = datetime.now(UTC)

        effective_limit_secs = (
            (machine.daily_limit_mins + snapshot.bonus_mins) * 60
            if machine.daily_limit_mins is not None
            else None
        )

        if (
            effective_limit_secs is not None
            and snapshot.active_seconds >= effective_limit_secs
            and snapshot.poweroff_at is None
        ):
            try:
                await lock_session(
                    machine.hostname,
                    machine.ssh_port,
                    machine.ssh_user,
                    machine.ssh_private_key,
                )
                if snapshot.locked_at is None:
                    snapshot.locked_at = datetime.now(UTC)
                    logger.info("Soft lock applied to %s", machine.friendly_name)
                    if notifier:
                        await notifier.notify_change(
                            "lock_linux",
                            machine.child_id,
                            machine.friendly_name,
                            "poller",
                        )
                else:
                    logger.debug(
                        "Re-applied lock to %s (user dismissed lock screen)",
                        machine.friendly_name,
                    )
            except Exception:
                logger.warning("Lock failed for %s", machine.friendly_name)

        if snapshot.locked_at is not None and snapshot.poweroff_at is None:
            elapsed = (datetime.now(UTC) - snapshot.locked_at).total_seconds()
            if elapsed >= machine.grace_period_mins * 60:
                try:
                    await poweroff_machine(
                        machine.hostname,
                        machine.ssh_port,
                        machine.ssh_user,
                        machine.ssh_private_key,
                    )
                    snapshot.poweroff_at = datetime.now(UTC)
                    logger.info("Hard poweroff applied to %s", machine.friendly_name)
                    if notifier:
                        await notifier.notify_change(
                            "poweroff_linux",
                            machine.child_id,
                            machine.friendly_name,
                            "poller",
                        )
                except Exception:
                    snapshot.poweroff_at = datetime.now(UTC)
                    logger.warning(
                        "Poweroff failed for %s — marking as powered off to stop retries",
                        machine.friendly_name,
                    )

        await session.commit()


async def poller_loop(notifier: DiscordNotifier | None = None) -> None:
    """Main poll loop — iterates all enabled machines every POLL_INTERVAL seconds.

    Args:
        notifier: Optional Discord notifier passed down to each poll_machine call.
    """
    while True:
        try:
            async with make_session() as session:
                result = await session.execute(
                    select(LinuxMachine).where(LinuxMachine.enabled.is_(True))
                )
                machines = result.scalars().all()

            await asyncio.gather(
                *[poll_machine(m, notifier=notifier) for m in machines],
                return_exceptions=True,
            )
        except Exception:
            logger.exception("Poller cycle failed")
        await asyncio.sleep(POLL_INTERVAL)
