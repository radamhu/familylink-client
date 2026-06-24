"""Tests for Discord UI action views."""

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


def _make_interaction(role_names=("Parent",)):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    member = MagicMock(spec=discord.Member)
    roles = [MagicMock(spec=discord.Role, name=n) for n in role_names]
    for role, name in zip(roles, role_names, strict=False):
        role.name = name
    member.roles = roles
    interaction.user = member
    interaction.response = AsyncMock()
    return interaction


async def test_app_block_view_unblock_calls_service():
    """Unblock button calls always_allow_app and sends a response."""
    from familylink_server.bot.views import AppBlockView

    svc = AsyncMock()
    notifier = AsyncMock()
    view = AppBlockView(svc, notifier, "com.tiktok", "uid-1", "Emma")

    interaction = _make_interaction()
    await view._unblock(interaction, MagicMock())

    svc.always_allow_app.assert_awaited_once_with("com.tiktok", child_id="uid-1")
    interaction.response.send_message.assert_awaited_once()


async def test_app_block_view_always_allow_calls_service():
    """Always Allow button calls always_allow_app."""
    from familylink_server.bot.views import AppBlockView

    svc = AsyncMock()
    notifier = AsyncMock()
    view = AppBlockView(svc, notifier, "com.tiktok", "uid-1", "Emma")

    interaction = _make_interaction()
    await view._always_allow(interaction, MagicMock())

    svc.always_allow_app.assert_awaited_once_with("com.tiktok", child_id="uid-1")


async def test_device_lock_view_unlock_calls_service():
    """Unlock button calls unlock_device."""
    from familylink_server.bot.views import DeviceLockView

    svc = AsyncMock()
    notifier = AsyncMock()
    view = DeviceLockView(svc, notifier, "d-1", "uid-1", "Emma")

    interaction = _make_interaction()
    await view._unlock(interaction, MagicMock())

    svc.unlock_device.assert_awaited_once_with("d-1", child_id="uid-1")


async def test_summary_view_lock_device_calls_service():
    """Lock Device button calls lock_device."""
    from familylink_server.bot.views import SummaryView

    svc = AsyncMock()
    notifier = AsyncMock()
    view = SummaryView(svc, notifier, "uid-1", "Emma", "d-1")

    interaction = _make_interaction()
    await view._lock_device(interaction, MagicMock())

    svc.lock_device.assert_awaited_once_with("d-1", child_id="uid-1")


async def test_app_block_view_unauthorized():
    """Unauthorized user gets ephemeral error and service is not called."""
    from familylink_server.bot.views import AppBlockView

    svc = AsyncMock()
    notifier = AsyncMock()
    view = AppBlockView(svc, notifier, "com.tiktok", "uid-1", "Emma")

    interaction = _make_interaction(role_names=("Member",))
    await view._unblock(interaction, MagicMock())

    svc.always_allow_app.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.call_args.kwargs
    assert msg.get("ephemeral") is True
