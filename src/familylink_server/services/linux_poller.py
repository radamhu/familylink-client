"""Background asyncio task that polls Linux machines and enforces screen-time limits."""

import asyncio
import logging
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot
from familylink_server.db.session import make_session
from familylink_server.services.linux_ssh import (
    check_session,
    lock_session,
    poweroff_machine,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60


async def poll_machine(machine: LinuxMachine) -> None:
    """Poll one machine: skip if powered off, accumulate active seconds, enforce limits.

    Args:
        machine: The LinuxMachine ORM instance to poll.
    """
    today = date.today()

    # Early exit without SSH if already powered off today
    async with make_session() as session:
        stmt = select(LinuxUsageSnapshot).where(
            LinuxUsageSnapshot.machine_id == machine.id,
            LinuxUsageSnapshot.date == today,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.poweroff_at is not None:
            return

    try:
        active = await check_session(
            machine.hostname,
            machine.ssh_port,
            machine.ssh_user,
            machine.ssh_private_key,
        )
    except Exception:
        logger.warning("SSH poll failed for %s", machine.friendly_name)
        return

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

        if active:
            snapshot.active_seconds += POLL_INTERVAL
            snapshot.updated_at = datetime.now(UTC)

        if (
            machine.daily_limit_mins is not None
            and snapshot.active_seconds >= machine.daily_limit_mins * 60
            and snapshot.locked_at is None
        ):
            try:
                await lock_session(
                    machine.hostname,
                    machine.ssh_port,
                    machine.ssh_user,
                    machine.ssh_private_key,
                )
                snapshot.locked_at = datetime.now(UTC)
                logger.info("Soft lock applied to %s", machine.friendly_name)
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
                except Exception:
                    # Mark failed poweroff attempts so the loop doesn't retry forever.
                    # The machine will be re-attempted next day when poweroff_at resets.
                    snapshot.poweroff_at = datetime.now(UTC)
                    logger.warning(
                        "Poweroff failed for %s — marking as powered off to stop retries",
                        machine.friendly_name,
                    )

        await session.commit()


async def poller_loop() -> None:
    """Main poll loop — iterates all enabled machines every POLL_INTERVAL seconds."""
    while True:
        try:
            async with make_session() as session:
                result = await session.execute(
                    select(LinuxMachine).where(LinuxMachine.enabled.is_(True))
                )
                machines = result.scalars().all()

            await asyncio.gather(
                *[poll_machine(m) for m in machines],
                return_exceptions=True,
            )
        except Exception:
            logger.exception("Poller cycle failed")
        await asyncio.sleep(POLL_INTERVAL)
