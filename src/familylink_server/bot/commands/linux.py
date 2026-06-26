"""Discord /linux command group."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from familylink_server.bot.commands import require_discord_role
from familylink_server.db.models import AuditLog, LinuxMachine, LinuxUsageSnapshot
from familylink_server.services.linux_ssh import unlock_session

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession


class LinuxGroup(app_commands.Group, name="linux", description="Manage Linux machines"):
    """Slash command group: /linux bonus."""

    def __init__(
        self,
        make_session: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    ) -> None:
        super().__init__()
        self._make_session = make_session

    @app_commands.command(
        name="bonus", description="Grant extra screen time to a Linux machine"
    )
    @app_commands.describe(machine="Machine name", minutes="Extra minutes to grant")
    @app_commands.choices(
        minutes=[
            app_commands.Choice(name="+15 min", value=15),
            app_commands.Choice(name="+30 min", value=30),
            app_commands.Choice(name="+60 min", value=60),
        ]
    )
    async def bonus(
        self,
        interaction: discord.Interaction,
        machine: str,
        minutes: int,
    ) -> None:
        """Grant bonus minutes to a machine, unlocking if currently locked."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                "Insufficient permissions.", ephemeral=True
            )
            return
        try:
            machine_id = int(machine)
        except ValueError:
            await interaction.response.send_message(
                "Invalid machine selection.", ephemeral=True
            )
            return

        async with self._make_session() as session:
            db_machine = await session.get(LinuxMachine, machine_id)
            if db_machine is None:
                await interaction.response.send_message(
                    "Machine not found.", ephemeral=True
                )
                return

            today = date.today()
            stmt = select(LinuxUsageSnapshot).where(
                LinuxUsageSnapshot.machine_id == machine_id,
                LinuxUsageSnapshot.date == today,
            )
            snapshot = (await session.execute(stmt)).scalar_one_or_none()
            now = datetime.now(UTC)
            if snapshot is None:
                snapshot = LinuxUsageSnapshot(
                    machine_id=machine_id,
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
                    now = datetime.now(UTC)

            snapshot.bonus_mins += minutes
            unlocked = False
            if snapshot.locked_at is not None and snapshot.poweroff_at is None:
                try:
                    await unlock_session(
                        db_machine.hostname,
                        db_machine.ssh_port,
                        db_machine.ssh_user,
                        db_machine.ssh_private_key,
                    )
                    snapshot.locked_at = None
                    unlocked = True
                except Exception:
                    pass

            snapshot.updated_at = datetime.now(UTC)
            session.add(
                AuditLog(
                    child_id=db_machine.child_id,
                    action="bonus_linux",
                    target=db_machine.friendly_name,
                    new_value=str(minutes),
                    occurred_at=datetime.now(UTC),
                )
            )
            await session.commit()

        msg = f"⏰ +{minutes} min granted for **{db_machine.friendly_name}**."
        if unlocked:
            msg += " Machine unlocked."
        await interaction.response.send_message(msg, ephemeral=True)

    @bonus.autocomplete("machine")
    async def machine_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete: return enabled machines whose name contains `current`."""
        async with self._make_session() as session:
            result = await session.execute(
                select(LinuxMachine).where(LinuxMachine.enabled.is_(True))
            )
            machines = result.scalars().all()
        return [
            app_commands.Choice(name=m.friendly_name, value=str(m.id))
            for m in machines
            if current.lower() in m.friendly_name.lower()
        ][:25]
