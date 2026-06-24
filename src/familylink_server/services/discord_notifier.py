"""Outbound Discord notification service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _change_embed(
    action: str, child_name: str, target: str, source: str
) -> discord.Embed:
    """Build a change-alert embed.  Full embed builder lives in bot.embeds once that module exists."""
    action_map = {
        "block": ("🔒 App Blocked", discord.Color.red()),
        "always_allow": ("✅ App Always Allowed", discord.Color.green()),
        "set_limit": ("⏱️ App Limit Set", discord.Color.orange()),
        "lock_device": ("🔒 Device Locked", discord.Color.orange()),
        "unlock_device": ("🔓 Device Unlocked", discord.Color.green()),
    }
    title, color = action_map.get(
        action, (f"ℹ️ {action.replace('_', ' ').title()}", discord.Color.blurple())
    )
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Child", value=child_name, inline=True)
    embed.add_field(name="Target", value=target, inline=True)
    embed.add_field(name="By", value=source, inline=True)
    return embed


def _summary_embed(
    child_name: str, top_apps: list[dict], total_seconds: int
) -> discord.Embed:
    """Build a daily summary embed."""
    import datetime

    today = datetime.date.today()
    today_str = f"{today.strftime('%A')} {today.day} {today.strftime('%b')}"
    h, rem = divmod(total_seconds, 3600)
    m = rem // 60
    total_str = f"{h}h {m:02d}m" if h else f"{m}m"
    embed = discord.Embed(
        title=f"📊 Daily Summary — {child_name}  ·  {today_str}",
        description=f"Total screen time: **{total_str}**",
        color=discord.Color.blurple(),
    )
    max_s = max((a["seconds"] for a in top_apps), default=1)
    for app in top_apps[:5]:
        ah, ar = divmod(app["seconds"], 3600)
        am = ar // 60
        dur = f"{ah}h {am:02d}m" if ah else f"{am}m"
        filled = round(app["seconds"] / max_s * 10)
        bar = "█" * filled + "░" * (10 - filled)
        embed.add_field(name=app["title"], value=f"`{bar}` {dur}", inline=False)
    return embed


class DiscordNotifier:
    """Sends embeds to a configured Discord channel."""

    def __init__(self, channel_id: int) -> None:
        self._channel_id = channel_id
        self._channel: discord.TextChannel | None = None

    def set_channel(self, channel: discord.TextChannel) -> None:
        """Called by the bot's on_ready once the channel is resolved."""
        self._channel = channel
        logger.info("Discord notification channel set: #%s", channel.name)

    async def notify_change(
        self,
        action: str,
        child_name: str,
        target: str,
        source: str,
        view: discord.ui.View | None = None,
    ) -> None:
        """Post a change-alert embed. No-op if channel not yet ready."""
        if self._channel is None:
            return
        embed = _change_embed(action, child_name, target, source)
        await self._channel.send(embed=embed, view=view)

    async def post_daily_summary(
        self,
        child_name: str,
        top_apps: list[dict],
        total_seconds: int,
        view: discord.ui.View | None = None,
    ) -> None:
        """Post a daily usage summary embed. No-op if channel not yet ready."""
        if self._channel is None:
            return
        embed = _summary_embed(child_name, top_apps, total_seconds)
        await self._channel.send(embed=embed, view=view)


_notifier: DiscordNotifier | None = None


def init_notifier(channel_id: int) -> DiscordNotifier:
    """Create and store the singleton. Called once in lifespan."""
    global _notifier
    _notifier = DiscordNotifier(channel_id)
    return _notifier


def get_notifier() -> DiscordNotifier | None:
    """Return the singleton, or None when Discord is disabled."""
    return _notifier
