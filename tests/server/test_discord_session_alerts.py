"""Tests for Discord session expired/restored alert methods."""

from unittest.mock import AsyncMock

import discord
import pytest

from familylink_server.services.discord_notifier import DiscordNotifier


@pytest.fixture
def notifier():
    """Create a DiscordNotifier instance for testing."""
    return DiscordNotifier(channel_id=123)


@pytest.fixture
def channel():
    """Create a mock Discord TextChannel."""
    ch = AsyncMock(spec=discord.TextChannel)
    ch.name = "family-alerts"
    return ch


async def test_notify_session_expired_posts_embed(notifier, channel):
    """notify_session_expired sends an embed with 'expired' in the title."""
    notifier.set_channel(channel)
    await notifier.notify_session_expired()
    channel.send.assert_awaited_once()
    embed = channel.send.call_args.kwargs["embed"]
    assert "expired" in embed.title.lower()


async def test_notify_session_restored_posts_embed(notifier, channel):
    """notify_session_restored sends an embed with 'restored' in the title."""
    notifier.set_channel(channel)
    await notifier.notify_session_restored()
    channel.send.assert_awaited_once()
    embed = channel.send.call_args.kwargs["embed"]
    assert "restored" in embed.title.lower()


async def test_session_alerts_noop_without_channel(notifier):
    """Both methods are silent no-ops when the Discord channel is not yet set."""
    await notifier.notify_session_expired()
    await notifier.notify_session_restored()
