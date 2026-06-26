"""Tests for the /linux Discord command group."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord


def _make_interaction(has_role: bool = True) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    member = MagicMock(spec=discord.Member)
    allowed_role = MagicMock()
    allowed_role.name = "FamilyAdmin"
    member.roles = [allowed_role] if has_role else []
    interaction.user = member
    interaction.response = AsyncMock()
    return interaction


def _make_machine(machine_id: int = 1, friendly_name: str = "Gaming PC") -> MagicMock:
    m = MagicMock()
    m.id = machine_id
    m.child_id = "child1"
    m.friendly_name = friendly_name
    m.hostname = "host"
    m.ssh_port = 22
    m.ssh_user = "user"
    m.ssh_private_key = "key"
    m.daily_limit_mins = 60
    m.enabled = True
    return m


def _make_session_ctx(machine=None, snapshot=None):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=machine)
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = snapshot
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


async def test_linux_bonus_grants_minutes():
    """'/linux bonus' adds bonus_mins to snapshot and replies with confirmation."""
    from familylink_server.bot.commands.linux import LinuxGroup

    machine = _make_machine()
    snap = MagicMock()
    snap.bonus_mins = 0
    snap.locked_at = None
    snap.poweroff_at = None
    snap.updated_at = None

    mock_ctx = _make_session_ctx(machine=machine, snapshot=snap)
    make_session = MagicMock(return_value=mock_ctx)

    group = LinuxGroup(make_session=make_session)
    interaction = _make_interaction()

    with patch(
        "familylink_server.bot.commands.linux.require_discord_role", return_value=True
    ):
        await group.bonus.callback(group, interaction, machine="1", minutes=15)

    assert snap.bonus_mins == 15
    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.call_args[0][0]
    assert "+15" in msg
    assert "Gaming PC" in msg


async def test_linux_bonus_unlocks_when_locked():
    """'/linux bonus' calls unlock_session and mentions unlock in reply when machine was locked."""
    import datetime

    from familylink_server.bot.commands.linux import LinuxGroup

    machine = _make_machine()
    snap = MagicMock()
    snap.bonus_mins = 0
    snap.locked_at = datetime.datetime.now(datetime.UTC)
    snap.poweroff_at = None
    snap.updated_at = None

    mock_ctx = _make_session_ctx(machine=machine, snapshot=snap)
    make_session = MagicMock(return_value=mock_ctx)

    group = LinuxGroup(make_session=make_session)
    interaction = _make_interaction()

    mock_unlock = AsyncMock()
    with (
        patch(
            "familylink_server.bot.commands.linux.require_discord_role",
            return_value=True,
        ),
        patch("familylink_server.bot.commands.linux.unlock_session", mock_unlock),
    ):
        await group.bonus.callback(group, interaction, machine="1", minutes=30)

    mock_unlock.assert_awaited_once()
    msg = interaction.response.send_message.call_args[0][0]
    assert "unlocked" in msg.lower()


async def test_linux_bonus_requires_role():
    """'/linux bonus' replies with permission error without the Discord role."""
    from familylink_server.bot.commands.linux import LinuxGroup

    make_session = MagicMock()
    group = LinuxGroup(make_session=make_session)
    interaction = _make_interaction(has_role=False)

    with patch(
        "familylink_server.bot.commands.linux.require_discord_role", return_value=False
    ):
        await group.bonus.callback(group, interaction, machine="1", minutes=15)

    msg = (
        interaction.response.send_message.call_args[1].get("content")
        or interaction.response.send_message.call_args[0][0]
    )
    assert "permission" in msg.lower() or "insufficient" in msg.lower()
