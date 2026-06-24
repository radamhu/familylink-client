"""Discord UI views (action button rows for embeds)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from familylink_server.bot.commands import require_discord_role

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

_TIMEOUT = 300


class AppBlockView(discord.ui.View):
    """Buttons shown after blocking an app: Unblock and Always Allow."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        package: str,
        child_id: str,
        child_name: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._package = package
        self._child_id = child_id
        self._child_name = child_name

    async def _unblock(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Handle Unblock button press."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        await self._svc.always_allow_app(self._package, child_id=self._child_id)
        await self._notifier.notify_change(
            "always_allow",
            self._child_name,
            self._package,
            interaction.user.display_name,
        )
        await interaction.response.send_message(
            f"✅ {self._package} unblocked for {self._child_name}.", ephemeral=True
        )
        self.stop()

    async def _always_allow(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Handle Always Allow button press."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        await self._svc.always_allow_app(self._package, child_id=self._child_id)
        await self._notifier.notify_change(
            "always_allow",
            self._child_name,
            self._package,
            interaction.user.display_name,
        )
        await interaction.response.send_message(
            f"✅ {self._package} always allowed for {self._child_name}.", ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Unblock", style=discord.ButtonStyle.success)
    async def _unblock_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._unblock(interaction, button)

    @discord.ui.button(label="Always Allow", style=discord.ButtonStyle.primary)
    async def _always_allow_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._always_allow(interaction, button)


class AppLimitView(discord.ui.View):
    """Button shown after setting an app limit: Undo (removes limit via always_allow)."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        package: str,
        child_id: str,
        child_name: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._package = package
        self._child_id = child_id
        self._child_name = child_name

    async def _undo(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Handle Undo button press."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        await self._svc.always_allow_app(self._package, child_id=self._child_id)
        await self._notifier.notify_change(
            "always_allow",
            self._child_name,
            self._package,
            interaction.user.display_name,
        )
        await interaction.response.send_message(
            f"↩️ Limit removed for {self._package}.", ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Undo", style=discord.ButtonStyle.secondary)
    async def _undo_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._undo(interaction, button)


class AppAllowView(discord.ui.View):
    """Button shown after always-allowing an app: Remove (blocks it)."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        package: str,
        child_id: str,
        child_name: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._package = package
        self._child_id = child_id
        self._child_name = child_name

    async def _remove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Handle Remove button press."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        await self._svc.block_app(self._package, child_id=self._child_id)
        await self._notifier.notify_change(
            "block", self._child_name, self._package, interaction.user.display_name
        )
        await interaction.response.send_message(
            f"\U0001f512 {self._package} blocked for {self._child_name}.",
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.danger)
    async def _remove_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._remove(interaction, button)


class DeviceLockView(discord.ui.View):
    """Button shown after locking a device: Unlock."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        device_id: str,
        child_id: str,
        child_name: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._device_id = device_id
        self._child_id = child_id
        self._child_name = child_name

    async def _unlock(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Handle Unlock button press."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        await self._svc.unlock_device(self._device_id, child_id=self._child_id)
        await self._notifier.notify_change(
            "unlock_device",
            self._child_name,
            self._device_id,
            interaction.user.display_name,
        )
        await interaction.response.send_message(
            "\U0001f513 Device unlocked.", ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Unlock", style=discord.ButtonStyle.success)
    async def _unlock_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._unlock(interaction, button)


class DeviceUnlockView(discord.ui.View):
    """Button shown after unlocking a device: Lock."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        device_id: str,
        child_id: str,
        child_name: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._device_id = device_id
        self._child_id = child_id
        self._child_name = child_name

    async def _lock(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Handle Lock button press."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        await self._svc.lock_device(self._device_id, child_id=self._child_id)
        await self._notifier.notify_change(
            "lock_device",
            self._child_name,
            self._device_id,
            interaction.user.display_name,
        )
        await interaction.response.send_message(
            "\U0001f512 Device locked.", ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Lock", style=discord.ButtonStyle.danger)
    async def _lock_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._lock(interaction, button)


class SummaryView(discord.ui.View):
    """Buttons on the daily summary embed: Lock Device."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        child_id: str,
        child_name: str,
        device_id: str | None,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._child_id = child_id
        self._child_name = child_name
        self._device_id = device_id

    async def _lock_device(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Handle Lock Device button press."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        if not self._device_id:
            await interaction.response.send_message(
                "No device found for this child.", ephemeral=True
            )
            return
        await self._svc.lock_device(self._device_id, child_id=self._child_id)
        await self._notifier.notify_change(
            "lock_device",
            self._child_name,
            self._device_id,
            interaction.user.display_name,
        )
        await interaction.response.send_message(
            "\U0001f512 Device locked.", ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Lock Device", style=discord.ButtonStyle.danger)
    async def _lock_device_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._lock_device(interaction, button)
