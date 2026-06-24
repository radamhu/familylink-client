"""Tests for bot authorization and child resolution helpers."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/familylink_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-bytes-exactly!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("FAMILYLINK_GOOGLE_EMAIL", "parent@gmail.com")
os.environ.setdefault("FAMILYLINK_COOKIES_B64", "dGVzdA==")
os.environ.setdefault("DISCORD_ALLOWED_ROLE", "Parent")

from unittest.mock import AsyncMock, MagicMock

import discord


def _make_interaction(role_names: list[str] | None = None) -> discord.Interaction:
    """Create a mock Discord interaction with specified roles."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    member = MagicMock(spec=discord.Member)
    roles = [MagicMock(spec=discord.Role) for _ in (role_names or [])]
    for role, name in zip(roles, (role_names or []), strict=False):
        role.name = name
    member.roles = roles
    interaction.user = member
    interaction.response = AsyncMock()
    return interaction


def test_require_discord_role_passes_with_role():
    """Test that role check passes when member has the required role."""
    from familylink_server.bot.commands import require_discord_role

    interaction = _make_interaction(["Parent", "Member"])
    assert require_discord_role(interaction) is True


def test_require_discord_role_fails_without_role():
    """Test that role check fails when member lacks the required role."""
    from familylink_server.bot.commands import require_discord_role

    interaction = _make_interaction(["Member"])
    assert require_discord_role(interaction) is False


def test_require_discord_role_fails_no_guild():
    """Test that role check fails when interaction has no guild."""
    from familylink_server.bot.commands import require_discord_role

    interaction = _make_interaction(["Parent"])
    interaction.guild = None
    assert require_discord_role(interaction) is False


async def test_resolve_child_single_child():
    """Test that resolve_child returns single child when no ID is provided."""
    from familylink_server.bot.commands import resolve_child

    svc = AsyncMock()
    member = MagicMock()
    member.user_id = "uid-1"
    member.profile.display_name = "Emma"
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    result = await resolve_child(svc, None)
    assert result == ("uid-1", "Emma")


async def test_resolve_child_multiple_children_no_id():
    """Test that resolve_child returns None when multiple children exist and no ID."""
    from familylink_server.bot.commands import resolve_child

    svc = AsyncMock()
    m1, m2 = MagicMock(), MagicMock()
    for m, uid, name in [(m1, "uid-1", "Emma"), (m2, "uid-2", "Tom")]:
        m.user_id = uid
        m.profile.display_name = name
        m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m1, m2])

    result = await resolve_child(svc, None)
    assert result is None  # ambiguous


async def test_resolve_child_explicit_id():
    """Test that resolve_child returns matching child when ID is provided."""
    from familylink_server.bot.commands import resolve_child

    svc = AsyncMock()
    member = MagicMock()
    member.user_id = "uid-1"
    member.profile.display_name = "Emma"
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    result = await resolve_child(svc, "uid-1")
    assert result == ("uid-1", "Emma")


async def test_apps_block_calls_service():
    """Test that /apps block calls block_app on the service."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier)

    # Single child, no child_id needed
    m = MagicMock()
    m.user_id = "uid-1"
    m.profile.display_name = "Emma"
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(["Parent"])
    await group.block.callback(group, interaction, package="com.tiktok", child="uid-1")

    svc.block_app.assert_awaited_once_with("com.tiktok", child_id="uid-1")
    interaction.response.send_message.assert_awaited_once()


async def test_apps_limit_calls_service():
    """Test that /apps limit calls set_app_limit on the service."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier)

    m = MagicMock()
    m.user_id = "uid-1"
    m.profile.display_name = "Emma"
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(["Parent"])
    await group.limit.callback(
        group, interaction, package="com.youtube", minutes=60, child="uid-1"
    )

    svc.set_app_limit.assert_awaited_once_with("com.youtube", 60, child_id="uid-1")


async def test_apps_allow_calls_service():
    """Test that /apps allow calls always_allow_app on the service."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier)

    m = MagicMock()
    m.user_id = "uid-1"
    m.profile.display_name = "Emma"
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(["Parent"])
    await group.allow.callback(group, interaction, package="com.youtube", child="uid-1")

    svc.always_allow_app.assert_awaited_once_with("com.youtube", child_id="uid-1")


async def test_apps_block_unauthorized():
    """Test that /apps block is rejected when the caller lacks the required role."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier)

    interaction = _make_interaction(["Member"])
    await group.block.callback(group, interaction, package="com.tiktok", child="uid-1")

    svc.block_app.assert_not_awaited()
    msg = interaction.response.send_message.call_args.kwargs
    assert msg.get("ephemeral") is True
