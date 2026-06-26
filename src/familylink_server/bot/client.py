"""Discord bot client and restart wrapper."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from familylink_server.bot.embeds import (
    daily_summary_embed,  # noqa: F401
)
from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession

    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

logger = logging.getLogger(__name__)


def _linux_rows_for_child(
    machines: list,
    snapshots: dict,
) -> list[dict]:
    """Build linux_machines list for a child given ORM machine objects and snap map."""
    rows = []
    for m in machines:
        snap = snapshots.get(m.id)
        active_mins = (snap.active_seconds // 60) if snap else 0
        bonus_mins = snap.bonus_mins if snap else 0
        effective_limit_mins = (
            m.daily_limit_mins + bonus_mins if m.daily_limit_mins is not None else None
        )
        if snap and snap.poweroff_at:
            lm_status = "powered_off"
        elif snap and snap.locked_at:
            lm_status = "locked"
        else:
            lm_status = "active"
        rows.append(
            {
                "friendly_name": m.friendly_name,
                "active_mins": active_mins,
                "effective_limit_mins": effective_limit_mins,
                "status": lm_status,
            }
        )
    return rows


async def _fetch_linux_rows(
    child_id: str,
    make_session: Callable[[], AbstractAsyncContextManager[AsyncSession]],
) -> list[dict]:
    """Query Linux machines + today's snapshots for one child."""
    today = date.today()
    async with make_session() as session:
        result = await session.execute(
            select(LinuxMachine).where(
                LinuxMachine.child_id == child_id,
                LinuxMachine.enabled.is_(True),
            )
        )
        machines = result.scalars().all()
        snap_map: dict[int, object] = {}
        for m in machines:
            snap_result = await session.execute(
                select(LinuxUsageSnapshot).where(
                    LinuxUsageSnapshot.machine_id == m.id,
                    LinuxUsageSnapshot.date == today,
                )
            )
            snap = snap_result.scalar_one_or_none()
            if snap:
                snap_map[m.id] = snap
    return _linux_rows_for_child(machines, snap_map)


class FamilyLinkBot(commands.Bot):
    """discord.py Bot subclass that wires in FamilyLinkService and DiscordNotifier."""

    def __init__(
        self,
        service: FamilyLinkService,
        notifier: DiscordNotifier,
        guild_id: int,
        summary_time: dt.time,
        make_session: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    ) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.service = service
        self.notifier = notifier
        self.guild_id = guild_id
        self._summary_time = summary_time
        self._make_session = make_session
        self.daily_summary_task: tasks.Loop | None = None

    async def setup_hook(self) -> None:
        """Register command groups and create the scheduled task."""
        guild = discord.Object(id=self.guild_id)

        try:
            from familylink_server.bot.commands.apps import AppsGroup
            from familylink_server.bot.commands.devices import DevicesGroup
            from familylink_server.bot.commands.linux import LinuxGroup
            from familylink_server.bot.commands.usage import (
                UsageGroup,
                make_refresh_command,
                make_status_command,
            )

            self.tree.add_command(AppsGroup(self.service, self.notifier), guild=guild)
            self.tree.add_command(
                DevicesGroup(self.service, self.notifier), guild=guild
            )
            self.tree.add_command(UsageGroup(self.service, self.notifier), guild=guild)
            self.tree.add_command(
                LinuxGroup(make_session=self._make_session), guild=guild
            )
            self.tree.add_command(
                make_status_command(self.service, self._make_session), guild=guild
            )
            self.tree.add_command(make_refresh_command(self.service), guild=guild)
        except ImportError:
            logger.warning(
                "Bot command modules not yet available — skipping command registration"
            )

        self.daily_summary_task = tasks.loop(time=self._summary_time)(
            self._run_daily_summary
        )

        @self.tree.error
        async def on_tree_error(
            interaction: discord.Interaction,
            error: app_commands.AppCommandError,
        ) -> None:
            if isinstance(error, app_commands.CheckFailure):
                await interaction.response.send_message(
                    "You do not have permission to use this command.",
                    ephemeral=True,
                )
            else:
                logger.exception("Unhandled app command error", exc_info=error)

    async def on_ready(self) -> None:
        """Sync command tree, resolve channel, start summary task."""
        guild = discord.Object(id=self.guild_id)
        await self.tree.sync(guild=guild)
        logger.info(
            "Discord bot ready as %s — commands synced to guild %s",
            self.user,
            self.guild_id,
        )

        channel = self.get_channel(self.notifier._channel_id)
        if isinstance(channel, discord.TextChannel):
            self.notifier.set_channel(channel)
        else:
            logger.warning(
                "Discord channel %s not found or not a text channel",
                self.notifier._channel_id,
            )

        if (
            self.daily_summary_task is not None
            and not self.daily_summary_task.is_running()
        ):
            self.daily_summary_task.start()

    async def _run_daily_summary(self) -> None:
        """Post a daily usage summary embed for each supervised child."""
        try:
            from familylink_server.bot.views import SummaryView
        except ImportError:
            SummaryView = None  # type: ignore[assignment]

        try:
            members = await self.service.get_members()
            supervised = [
                m
                for m in members.members
                if m.member_supervision_info
                and m.member_supervision_info.is_supervised_member
            ]
            for child in supervised:
                usage = await self.service.get_apps_and_usage(child.user_id)
                all_apps_with_usage = sorted(
                    [
                        {"title": app.title, "seconds": app.usage_today_seconds}
                        for app in usage.apps
                        if hasattr(app, "usage_today_seconds")
                        and app.usage_today_seconds
                    ],
                    key=lambda x: x["seconds"],
                    reverse=True,
                )
                total_seconds = sum(a["seconds"] for a in all_apps_with_usage)
                top_apps = all_apps_with_usage[:5]
                device_id = (
                    usage.device_info[0].device_id if usage.device_info else None
                )
                linux_rows = await _fetch_linux_rows(child.user_id, self._make_session)
                view = None
                if SummaryView is not None:
                    view = SummaryView(
                        self.service,
                        self.notifier,
                        child.user_id,
                        child.profile.display_name,
                        device_id,
                    )
                await self.notifier.post_daily_summary(
                    child.profile.display_name,
                    top_apps,
                    total_seconds,
                    linux_machines=linux_rows,
                    view=view,
                )
        except Exception:
            logger.exception("Error posting daily summary")


async def _bot_task_with_restart(bot: FamilyLinkBot, token: str) -> None:
    """Run bot.start() in a restart loop; exits cleanly on CancelledError."""
    while True:
        try:
            await bot.start(token)
        except asyncio.CancelledError:
            await bot.close()
            return
        except Exception:
            logger.exception("Discord bot crashed — restarting in 30 s")
            await asyncio.sleep(30)
