"""Shared helpers for bot command modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from familylink_server.config import settings

if TYPE_CHECKING:
    from familylink_server.services.family_link import FamilyLinkService


def require_discord_role(interaction: discord.Interaction) -> bool:
    """Return True when the invoking member has the configured Discord role."""
    if interaction.guild is None:
        return False
    if not isinstance(interaction.user, discord.Member):
        return False
    allowed = settings.discord_allowed_role
    return any(role.name == allowed for role in interaction.user.roles)


async def child_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete choices for the optional child parameter."""
    from familylink_server.services.family_link import get_service

    svc = get_service()
    members = await svc.get_members()
    supervised = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    return [
        app_commands.Choice(name=m.profile.display_name, value=m.user_id)
        for m in supervised
        if current.lower() in m.profile.display_name.lower()
    ]


async def resolve_child(
    service: FamilyLinkService,
    child_id: str | None,
) -> tuple[str, str] | None:
    """Resolve optional child_id to (user_id, display_name).

    Returns None when child_id is None and there are multiple children (caller
    should reply with an ephemeral error asking the user to specify).
    """
    members = await service.get_members()
    supervised = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    if child_id:
        for m in supervised:
            if m.user_id == child_id:
                return (m.user_id, m.profile.display_name)
        return None
    if len(supervised) == 1:
        m = supervised[0]
        return (m.user_id, m.profile.display_name)
    return None
