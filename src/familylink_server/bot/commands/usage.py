"""Discord /usage, /status, and /refresh commands."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from familylink_server.bot.commands import (
    child_autocomplete,
    require_discord_role,
    resolve_child,
)
from familylink_server.bot.embeds import (
    status_embed,
    usage_history_embed,
    usage_today_embed,
)

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService


class UsageGroup(app_commands.Group, name="usage", description="View usage statistics"):
    """Slash command group: /usage today | history."""

    def __init__(self, service: FamilyLinkService, notifier: DiscordNotifier) -> None:
        super().__init__()
        self._svc = service
        self._notifier = notifier

    @app_commands.command(
        name="today", description="Show today's app usage for a child"
    )
    @app_commands.describe(child="Which child")
    @app_commands.autocomplete(child=child_autocomplete)
    async def today(
        self, interaction: discord.Interaction, child: str | None = None
    ) -> None:
        """Show today's usage."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message(
                "Please specify a child with the `child` parameter.", ephemeral=True
            )
            return
        child_id, child_name = resolved
        usage = await self._svc.get_apps_and_usage(child_id)
        top_apps = sorted(
            [
                {"title": a.title, "seconds": getattr(a, "usage_today_seconds", 0) or 0}
                for a in usage.apps
            ],
            key=lambda x: x["seconds"],
            reverse=True,
        )[:10]
        total = sum(a["seconds"] for a in top_apps)
        embed = usage_today_embed(child_name, top_apps, total)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="history", description="Show daily usage totals for the last N days"
    )
    @app_commands.describe(child="Which child", days="Number of days (default 7)")
    @app_commands.autocomplete(child=child_autocomplete)
    async def history(
        self,
        interaction: discord.Interaction,
        child: str | None = None,
        days: int = 7,
    ) -> None:
        """Show usage history."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message(
                "Please specify a child with the `child` parameter.", ephemeral=True
            )
            return
        child_id, child_name = resolved
        usage = await self._svc.get_apps_and_usage(child_id)
        today_total = sum(getattr(a, "usage_today_seconds", 0) or 0 for a in usage.apps)
        daily_totals = [
            {"date": datetime.date.today().isoformat(), "seconds": today_total}
        ]
        embed = usage_history_embed(child_name, daily_totals, days)
        await interaction.response.send_message(embed=embed, ephemeral=True)


def make_status_command(service: FamilyLinkService) -> app_commands.Command:
    """Factory: return a /status app_commands.Command bound to service."""

    @app_commands.command(
        name="status",
        description="Show a dashboard overview of all children and devices",
    )
    async def status(interaction: discord.Interaction) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        members = await service.get_members()
        supervised = [
            m
            for m in members.members
            if m.member_supervision_info
            and m.member_supervision_info.is_supervised_member
        ]
        children_data = []
        for child in supervised:
            usage = await service.get_apps_and_usage(child.user_id)
            total = sum(getattr(a, "usage_today_seconds", 0) or 0 for a in usage.apps)
            children_data.append(
                {
                    "name": child.profile.display_name,
                    "total_seconds": total,
                    "device_count": len(usage.device_info),
                }
            )
        embed = status_embed(children_data)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    return status


def make_refresh_command(service: FamilyLinkService) -> app_commands.Command:
    """Factory: return a /refresh app_commands.Command bound to service."""

    @app_commands.command(
        name="refresh", description="Invalidate the cache for all children"
    )
    async def refresh(interaction: discord.Interaction) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        service._members_cache = None
        service._usage_cache = {}
        await interaction.response.send_message(
            "♻️ Cache cleared — next request will fetch fresh data.", ephemeral=True
        )

    return refresh
