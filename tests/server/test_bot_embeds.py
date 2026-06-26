"""Tests for bot embed builder functions."""

import discord
import pytest


@pytest.fixture(autouse=True)
def _ensure_bot_package(tmp_path):
    """Ensure bot package exists (no-op once Task 3 is done)."""


def test_change_embed_block():
    """Test block action embed."""
    from familylink_server.bot.embeds import change_embed

    embed = change_embed("block", "Emma", "TikTok", "web UI")
    assert "🔒" in embed.title
    assert "Blocked" in embed.title
    assert embed.color == discord.Color.red()
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Child"] == "Emma"
    assert fields["Target"] == "TikTok"
    assert fields["By"] == "web UI"


def test_change_embed_always_allow():
    """Test always_allow action embed."""
    from familylink_server.bot.embeds import change_embed

    embed = change_embed("always_allow", "Emma", "YouTube", "bot")
    assert embed.color == discord.Color.green()


def test_change_embed_set_limit():
    """Test set_limit action embed."""
    from familylink_server.bot.embeds import change_embed

    embed = change_embed("set_limit", "Emma", "Minecraft", "web UI")
    assert embed.color == discord.Color.orange()


def test_apps_list_embed():
    """Test apps list embed."""
    from familylink_server.bot.embeds import apps_list_embed

    apps = [
        {
            "title": "YouTube",
            "state": "limited",
            "state_label": "Limited 60 min",
            "package_name": "com.youtube",
        },
        {
            "title": "TikTok",
            "state": "blocked",
            "state_label": "Blocked",
            "package_name": "com.tiktok",
        },
    ]
    embed = apps_list_embed(apps, child_name="Emma", page=1, total_pages=1)
    assert "Emma" in embed.title
    assert len(embed.fields) == len(apps)


def test_devices_list_embed():
    """Test devices list embed."""
    from familylink_server.bot.embeds import devices_list_embed

    devices = [{"friendly_name": "Emma Phone", "device_id": "d1", "is_locked": False}]
    embed = devices_list_embed(devices, child_name="Emma")
    assert "Emma" in embed.title
    assert len(embed.fields) == 1


def test_usage_today_embed_bar_chart():
    """Test usage today embed with bar chart."""
    from familylink_server.bot.embeds import usage_today_embed

    top_apps = [
        {"title": "YouTube", "seconds": 6300},
        {"title": "Minecraft", "seconds": 1800},
    ]
    embed = usage_today_embed("Emma", top_apps, total_seconds=8100)
    assert "Emma" in embed.title
    assert "█" in embed.description or any("█" in f.value for f in embed.fields)


def test_usage_history_embed():
    """Test usage history embed."""
    from familylink_server.bot.embeds import usage_history_embed

    daily = [
        {"date": "2026-06-24", "seconds": 7200},
        {"date": "2026-06-23", "seconds": 5400},
    ]
    embed = usage_history_embed("Emma", daily, days=7)
    assert "Emma" in embed.title
    assert len(embed.fields) == 2


def test_status_embed():
    """Test status embed."""
    from familylink_server.bot.embeds import status_embed

    children_data = [
        {"name": "Emma", "total_seconds": 7200, "device_count": 1},
        {"name": "Tom", "total_seconds": 3600, "device_count": 2},
    ]
    embed = status_embed(children_data)
    assert len(embed.fields) == 2


def test_daily_summary_embed_bar():
    """Test daily summary embed with bar chart."""
    from familylink_server.bot.embeds import daily_summary_embed

    top_apps = [
        {"title": "YouTube", "seconds": 6300},
        {"title": "Minecraft", "seconds": 3150},
    ]
    embed = daily_summary_embed("Emma", top_apps, total_seconds=9450)
    assert "Emma" in embed.title
    assert "3h" in embed.description or "2h" in embed.description
    assert any("█" in f.value for f in embed.fields)


def test_action_map_has_linux_actions():
    """_ACTION_MAP contains lock_linux, poweroff_linux, bonus_linux."""
    from familylink_server.bot.embeds import _ACTION_MAP

    assert "lock_linux" in _ACTION_MAP
    assert "poweroff_linux" in _ACTION_MAP
    assert "bonus_linux" in _ACTION_MAP


def test_status_embed_includes_linux_machines():
    """status_embed shows Linux machine info when linux_machines provided."""
    from familylink_server.bot.embeds import status_embed

    children_data = [
        {
            "name": "Alice",
            "total_seconds": 3600,
            "device_count": 1,
            "linux_machines": [
                {
                    "friendly_name": "Gaming PC",
                    "active_mins": 34,
                    "effective_limit_mins": 90,
                    "status": "active",
                }
            ],
        }
    ]
    embed = status_embed(children_data)
    field_values = " ".join(f.value for f in embed.fields)
    assert "Gaming PC" in field_values


def test_daily_summary_embed_includes_linux_machines():
    """daily_summary_embed shows Linux section when linux_machines provided."""
    from familylink_server.bot.embeds import daily_summary_embed

    embed = daily_summary_embed(
        "Alice",
        [{"title": "YouTube", "seconds": 1800}],
        1800,
        linux_machines=[
            {
                "friendly_name": "Homework PC",
                "active_mins": 20,
                "effective_limit_mins": 60,
                "status": "active",
            }
        ],
    )
    field_names = " ".join(f.name for f in embed.fields)
    field_values = " ".join(f.value for f in embed.fields)
    assert "Linux" in field_names or "Homework PC" in field_values
