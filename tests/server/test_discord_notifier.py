"""Tests for DiscordNotifier service."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest


@pytest.fixture()
def notifier():
    """Create a test notifier instance."""
    from familylink_server.services.discord_notifier import DiscordNotifier

    return DiscordNotifier(channel_id=111)


@pytest.fixture()
def channel():
    """Create a mock Discord TextChannel."""
    ch = AsyncMock(spec=discord.TextChannel)
    ch.name = "family-alerts"
    return ch


async def test_notify_change_no_op_before_channel_set(notifier):
    """Notifier should silently skip if channel not set."""
    # Should not raise, just silently skip
    await notifier.notify_change("block", "Emma", "TikTok", "web UI")


async def test_notify_change_sends_embed(notifier, channel):
    """Notifier should send embed when channel is set."""
    notifier.set_channel(channel)
    await notifier.notify_change("block", "Emma", "TikTok", "web UI")
    channel.send.assert_awaited_once()
    call_kwargs = channel.send.call_args.kwargs
    assert "embed" in call_kwargs
    assert call_kwargs["embed"].title is not None


async def test_notify_change_passes_view(notifier, channel):
    """Notifier should pass view parameter to channel.send."""
    notifier.set_channel(channel)
    view = MagicMock(spec=discord.ui.View)
    await notifier.notify_change("lock", "Emma", "device-1", "bot", view=view)
    call_kwargs = channel.send.call_args.kwargs
    assert call_kwargs["view"] is view


async def test_post_daily_summary_sends_embed(notifier, channel):
    """Notifier should send daily summary embed when channel is set."""
    notifier.set_channel(channel)
    top_apps = [
        {"title": "YouTube", "seconds": 6300},
        {"title": "Minecraft", "seconds": 3480},
    ]
    await notifier.post_daily_summary("Emma", top_apps, total_seconds=9780)
    channel.send.assert_awaited_once()
    call_kwargs = channel.send.call_args.kwargs
    assert "embed" in call_kwargs


def test_init_notifier_sets_singleton():
    """init_notifier should create and return the singleton."""
    from familylink_server.services import discord_notifier as mod

    mod._notifier = None
    notifier = mod.init_notifier(999)
    assert mod.get_notifier() is notifier
    assert notifier._channel_id == 999
    mod._notifier = None  # cleanup
