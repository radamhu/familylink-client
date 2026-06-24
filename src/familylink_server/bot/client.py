"""Discord bot client and restart wrapper."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from familylink_server.bot.embeds import (
    daily_summary_embed,  # noqa: F401 (imported for re-use by callers)
)

if TYPE_CHECKING:
    import datetime

    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

logger = logging.getLogger(__name__)


class FamilyLinkBot(commands.Bot):
    """discord.py Bot subclass that wires in FamilyLinkService and DiscordNotifier."""

    def __init__(
        self,
        service: FamilyLinkService,
        notifier: DiscordNotifier,
        guild_id: int,
        summary_time: datetime.time,
    ) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.service = service
        self.notifier = notifier
        self.guild_id = guild_id
        self._summary_time = summary_time
        self.daily_summary_task: tasks.Loop | None = None

    async def setup_hook(self) -> None:
        """Register command groups and create the scheduled task."""
        guild = discord.Object(id=self.guild_id)

        try:
            from familylink_server.bot.commands.apps import AppsGroup
            from familylink_server.bot.commands.devices import DevicesGroup
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
            self.tree.add_command(make_status_command(self.service), guild=guild)
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
                top_apps = sorted(
                    [
                        {"title": app.title, "seconds": app.usage_today_seconds}
                        for app in usage.apps
                        if hasattr(app, "usage_today_seconds")
                        and app.usage_today_seconds
                    ],
                    key=lambda x: x["seconds"],
                    reverse=True,
                )[:5]
                total_seconds = sum(a["seconds"] for a in top_apps)
                device_id = (
                    usage.device_info[0].device_id if usage.device_info else None
                )
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
