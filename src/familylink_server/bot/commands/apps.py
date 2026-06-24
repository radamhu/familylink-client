"""Discord /apps command group."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from familylink_server.bot.commands import (
    child_autocomplete,
    require_discord_role,
    resolve_child,
)
from familylink_server.bot.embeds import apps_list_embed

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

_PAGE_SIZE = 10


class AppsGroup(app_commands.Group, name="apps", description="Manage supervised apps"):
    """Slash command group: /apps list | limit | block | allow."""

    def __init__(self, service: FamilyLinkService, notifier: DiscordNotifier) -> None:
        super().__init__()
        self._svc = service
        self._notifier = notifier

    @app_commands.command(
        name="list", description="List apps and their current state for a child"
    )
    @app_commands.describe(
        child="Which child (required when supervising multiple children)",
        page="Page number",
    )
    @app_commands.autocomplete(child=child_autocomplete)
    async def list(
        self, interaction: discord.Interaction, child: str | None = None, page: int = 1
    ) -> None:
        """List paginated apps."""
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
        all_apps = sorted(
            [
                {
                    "title": a.title,
                    "package_name": a.package_name,
                    "state": "blocked"
                    if a.supervision_setting.hidden
                    else (
                        "limited"
                        if a.supervision_setting.usage_limit
                        else (
                            "allowed"
                            if a.supervision_setting.always_allowed_app_info
                            else "unmanaged"
                        )
                    ),
                    "state_label": "Blocked"
                    if a.supervision_setting.hidden
                    else (
                        f"Limited {a.supervision_setting.usage_limit.daily_usage_limit_mins} min"
                        if a.supervision_setting.usage_limit
                        else (
                            "Always allowed"
                            if a.supervision_setting.always_allowed_app_info
                            else "Unmanaged"
                        )
                    ),
                }
                for a in usage.apps
            ],
            key=lambda x: x["title"].lower(),
        )
        total_pages = max(1, (len(all_apps) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        page = max(1, min(page, total_pages))
        page_apps = all_apps[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]
        embed = apps_list_embed(page_apps, child_name, page, total_pages)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="limit", description="Set a daily time limit for an app")
    @app_commands.describe(
        package="App package name (e.g. com.zhiliaoapp.musically)",
        minutes="Daily limit in minutes",
        child="Which child",
    )
    @app_commands.autocomplete(child=child_autocomplete)
    async def limit(
        self,
        interaction: discord.Interaction,
        package: str,
        minutes: int,
        child: str | None = None,
    ) -> None:
        """Set a daily usage limit."""
        from familylink_server.bot.views import AppLimitView

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
        await self._svc.set_app_limit(package, minutes, child_id=child_id)
        await self._notifier.notify_change(
            "set_limit",
            child_name,
            f"{package} ({minutes} min)",
            interaction.user.display_name,
        )
        view = AppLimitView(self._svc, self._notifier, package, child_id, child_name)
        await interaction.response.send_message(
            f"⏱️ Limit set: **{minutes} min/day** for `{package}` ({child_name}).",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="block", description="Block an app for a child")
    @app_commands.describe(package="App package name", child="Which child")
    @app_commands.autocomplete(child=child_autocomplete)
    async def block(
        self, interaction: discord.Interaction, package: str, child: str | None = None
    ) -> None:
        """Block an app."""
        from familylink_server.bot.views import AppBlockView

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
        await self._svc.block_app(package, child_id=child_id)
        await self._notifier.notify_change(
            "block", child_name, package, interaction.user.display_name
        )
        view = AppBlockView(self._svc, self._notifier, package, child_id, child_name)
        await interaction.response.send_message(
            f"\U0001f512 `{package}` blocked for {child_name}.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="allow", description="Always allow an app for a child")
    @app_commands.describe(package="App package name", child="Which child")
    @app_commands.autocomplete(child=child_autocomplete)
    async def allow(
        self, interaction: discord.Interaction, package: str, child: str | None = None
    ) -> None:
        """Always-allow an app."""
        from familylink_server.bot.views import AppAllowView

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
        await self._svc.always_allow_app(package, child_id=child_id)
        await self._notifier.notify_change(
            "always_allow", child_name, package, interaction.user.display_name
        )
        view = AppAllowView(self._svc, self._notifier, package, child_id, child_name)
        await interaction.response.send_message(
            f"✅ `{package}` always allowed for {child_name}.",
            view=view,
            ephemeral=True,
        )
