"""Discord /devices command group."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from familylink_server.bot.commands import (
    child_autocomplete,
    require_discord_role,
    resolve_child,
)
from familylink_server.bot.embeds import devices_list_embed

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService


class DevicesGroup(
    app_commands.Group, name="devices", description="Manage supervised devices"
):
    """Slash command group: /devices list | lock | unlock."""

    def __init__(self, service: FamilyLinkService, notifier: DiscordNotifier) -> None:
        super().__init__()
        self._svc = service
        self._notifier = notifier

    @app_commands.command(
        name="list", description="List devices and their lock state for a child"
    )
    @app_commands.describe(child="Which child")
    @app_commands.autocomplete(child=child_autocomplete)
    async def list(
        self, interaction: discord.Interaction, child: str | None = None
    ) -> None:
        """List devices."""
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
        devices = [
            {
                "device_id": d.device_id,
                "friendly_name": d.display_info.friendly_name,
                "is_locked": False,
            }
            for d in usage.device_info
        ]
        embed = devices_list_embed(devices, child_name)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="lock", description="Lock a device")
    @app_commands.describe(device="Device ID", child="Which child")
    @app_commands.autocomplete(child=child_autocomplete)
    async def lock(
        self, interaction: discord.Interaction, device: str, child: str | None = None
    ) -> None:
        """Lock a device."""
        from familylink_server.bot.views import DeviceLockView

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
        await self._svc.lock_device(device, child_id=child_id)
        await self._notifier.notify_change(
            "lock_device", child_name, device, interaction.user.display_name
        )
        view = DeviceLockView(self._svc, self._notifier, device, child_id, child_name)
        await interaction.response.send_message(
            f"🔒 Device `{device}` locked for {child_name}.", view=view, ephemeral=True
        )

    @app_commands.command(name="unlock", description="Unlock a device")
    @app_commands.describe(device="Device ID", child="Which child")
    @app_commands.autocomplete(child=child_autocomplete)
    async def unlock(
        self, interaction: discord.Interaction, device: str, child: str | None = None
    ) -> None:
        """Unlock a device."""
        from familylink_server.bot.views import DeviceUnlockView

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
        await self._svc.unlock_device(device, child_id=child_id)
        await self._notifier.notify_change(
            "unlock_device", child_name, device, interaction.user.display_name
        )
        view = DeviceUnlockView(self._svc, self._notifier, device, child_id, child_name)
        await interaction.response.send_message(
            f"🔓 Device `{device}` unlocked for {child_name}.",
            view=view,
            ephemeral=True,
        )
