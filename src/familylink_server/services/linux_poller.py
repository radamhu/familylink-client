"""Background asyncio task that polls Linux machines and enforces screen-time limits."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from familylink_server.config import settings
from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot
from familylink_server.db.session import make_session
from familylink_server.services.linux_ssh import (
    check_session,
    lock_session,
    poweroff_machine,
    unlock_session,
)

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.ntfy_notifier import NtfyNotifier

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60
LOW_TIME_THRESHOLD_SECS = 15 * 60

# Bedtime windows are entered and displayed as household wall-clock time, not
# UTC — settings.local_timezone (default Europe/Budapest) is the conversion
# used when comparing the current instant against window_start_time/
# window_end_time. The server process itself may run in any tz (prod runs
# UTC per docker-compose).
LOCAL_TZ = ZoneInfo(settings.local_timezone)


def _in_window(now: time, start: time | None, end: time | None) -> bool:
    """True when `now` falls in [start, end), wrapping past midnight if start > end.

    Either bound missing, or start == end, means no window is enforced.
    """
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def _shift_time_later(t: time, minutes: int) -> time:
    """Shift a time-of-day forward by `minutes`, wrapping past midnight."""
    shifted = datetime.combine(date.min, t) + timedelta(minutes=minutes)
    return shifted.time()


async def poll_machine(
    machine: LinuxMachine,
    notifier: DiscordNotifier | None = None,
    ntfy: NtfyNotifier | None = None,
    now: datetime | None = None,
) -> None:
    """Poll one machine: skip if powered off, accumulate active seconds, enforce limits.

    Args:
        machine: The LinuxMachine ORM instance to poll.
        notifier: Optional Discord notifier; posts on lock/poweroff when provided.
        ntfy: Optional ntfy notifier; posts a low-time warning when provided.
        now: Current time, injectable for tests; defaults to datetime.now(UTC).
    """
    now = now if now is not None else datetime.now(UTC)
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
                updated_at=now,
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
            logger.warning('SSH poll failed for %s', machine.friendly_name)
            # Machine went offline while locked (e.g. child held the power button).
            # poweroff_at was never set via the normal enforcement path, so the UI
            # would show "locked" indefinitely. Mark it as powered off here so the
            # status reflects reality. On next successful SSH the poller clears
            # poweroff_at and immediately re-enforces.
            if snapshot.locked_at is not None and snapshot.poweroff_at is None:
                snapshot.poweroff_at = now
                snapshot.updated_at = now
                logger.info(
                    'Machine %s unreachable while locked — marking as powered off',
                    machine.friendly_name,
                )
                await session.commit()
            return

        if snapshot.poweroff_at is not None:
            snapshot.poweroff_at = None
            logger.info(
                'Machine %s back online after poweroff — will re-enforce immediately',
                machine.friendly_name,
            )

        if active:
            snapshot.active_seconds += POLL_INTERVAL
            snapshot.updated_at = now

        effective_limit_secs = (
            (machine.daily_limit_mins + snapshot.bonus_mins) * 60
            if machine.daily_limit_mins is not None
            else None
        )
        effective_window_start = (
            _shift_time_later(machine.window_start_time, snapshot.bonus_mins)
            if machine.window_start_time is not None
            else None
        )
        in_window = _in_window(
            now.astimezone(LOCAL_TZ).time(),
            effective_window_start,
            machine.window_end_time,
        )

        if (
            effective_limit_secs is not None
            and not snapshot.low_time_alerted
            and snapshot.locked_at is None
        ):
            remaining_secs = effective_limit_secs - snapshot.active_seconds
            if 0 < remaining_secs <= LOW_TIME_THRESHOLD_SECS:
                snapshot.low_time_alerted = True
                if ntfy:
                    await ntfy.notify_low_time(
                        machine.child_id, machine.friendly_name, remaining_secs // 60
                    )

        if (
            (
                effective_limit_secs is not None
                and snapshot.active_seconds >= effective_limit_secs
            )
            or in_window
        ) and snapshot.poweroff_at is None:
            try:
                await lock_session(
                    machine.hostname,
                    machine.ssh_port,
                    machine.ssh_user,
                    machine.ssh_private_key,
                )
                if snapshot.locked_at is None:
                    snapshot.locked_at = now
                    logger.info('Soft lock applied to %s', machine.friendly_name)
                    if notifier:
                        await notifier.notify_change(
                            'lock_linux',
                            machine.child_id,
                            machine.friendly_name,
                            'poller',
                        )
                else:
                    logger.debug(
                        'Re-applied lock to %s (user dismissed lock screen)',
                        machine.friendly_name,
                    )
            except Exception:
                logger.warning('Lock failed for %s', machine.friendly_name)

        if snapshot.locked_at is not None and snapshot.poweroff_at is None:
            # If a bonus was granted after the lock, the kid may now be under the
            # effective limit. Unlock and clear rather than continuing toward poweroff.
            # Only applies when a cap is actually configured — with no cap there's
            # nothing for a bonus to have fixed, so a lock (manual, or otherwise)
            # must proceed to grace/poweroff like normal. Still enforced while
            # in_window regardless of usage — bedtime doesn't lift just because
            # the daily cap has headroom.
            if not in_window and (
                effective_limit_secs is not None
                and snapshot.active_seconds < effective_limit_secs
            ):
                # Best-effort unlock; locked_at must be cleared regardless so the
                # poller doesn't keep counting elapsed time toward poweroff.
                try:
                    await unlock_session(
                        machine.hostname,
                        machine.ssh_port,
                        machine.ssh_user,
                        machine.ssh_private_key,
                    )
                except Exception:
                    logger.warning(
                        'Unlock after bonus failed for %s — lock cleared in DB anyway',
                        machine.friendly_name,
                    )
                snapshot.locked_at = None
                logger.info(
                    'Cleared lock for %s — bonus brought usage back under effective limit',
                    machine.friendly_name,
                )
            else:
                elapsed = (now - snapshot.locked_at).total_seconds()
                if elapsed >= machine.grace_period_mins * 60:
                    try:
                        await poweroff_machine(
                            machine.hostname,
                            machine.ssh_port,
                            machine.ssh_user,
                            machine.ssh_private_key,
                        )
                        snapshot.poweroff_at = now
                        logger.info(
                            'Hard poweroff applied to %s', machine.friendly_name
                        )
                        if notifier:
                            await notifier.notify_change(
                                'poweroff_linux',
                                machine.child_id,
                                machine.friendly_name,
                                'poller',
                            )
                    except Exception:
                        snapshot.poweroff_at = now
                        logger.warning(
                            'Poweroff failed for %s — marking as powered off to stop retries',
                            machine.friendly_name,
                        )

        await session.commit()


async def poller_loop(
    notifier: DiscordNotifier | None = None, ntfy: NtfyNotifier | None = None
) -> None:
    """Main poll loop — iterates all enabled machines every POLL_INTERVAL seconds.

    Args:
        notifier: Optional Discord notifier passed down to each poll_machine call.
        ntfy: Optional ntfy notifier passed down to each poll_machine call.
    """
    while True:
        try:
            async with make_session() as session:
                result = await session.execute(
                    select(LinuxMachine).where(LinuxMachine.enabled.is_(True))
                )
                machines = result.scalars().all()

            await asyncio.gather(
                *[poll_machine(m, notifier=notifier, ntfy=ntfy) for m in machines],
                return_exceptions=True,
            )
        except Exception:
            logger.exception('Poller cycle failed')
        await asyncio.sleep(POLL_INTERVAL)
