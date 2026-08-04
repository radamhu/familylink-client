"""Tests for bot authorization and child resolution helpers."""

import os

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://localhost/familylink_test')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-32-bytes-exactly!')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'test-client-id')
os.environ.setdefault('GOOGLE_CLIENT_SECRET', 'test-client-secret')
os.environ.setdefault('FAMILYLINK_GOOGLE_EMAIL', 'parent@gmail.com')
os.environ.setdefault('FAMILYLINK_COOKIES_B64', 'dGVzdA==')
os.environ.setdefault('DISCORD_ALLOWED_ROLE', 'Parent')

from unittest import mock
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

    interaction = _make_interaction(['Parent', 'Member'])
    assert require_discord_role(interaction) is True


def test_require_discord_role_fails_without_role():
    """Test that role check fails when member lacks the required role."""
    from familylink_server.bot.commands import require_discord_role

    interaction = _make_interaction(['Member'])
    assert require_discord_role(interaction) is False


def test_require_discord_role_fails_no_guild():
    """Test that role check fails when interaction has no guild."""
    from familylink_server.bot.commands import require_discord_role

    interaction = _make_interaction(['Parent'])
    interaction.guild = None
    assert require_discord_role(interaction) is False


async def test_resolve_child_single_child():
    """Test that resolve_child returns single child when no ID is provided."""
    from familylink_server.bot.commands import resolve_child

    svc = AsyncMock()
    member = MagicMock()
    member.user_id = 'uid-1'
    member.profile.display_name = 'Emma'
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    result = await resolve_child(svc, None)
    assert result == ('uid-1', 'Emma')


async def test_resolve_child_multiple_children_no_id():
    """Test that resolve_child returns None when multiple children exist and no ID."""
    from familylink_server.bot.commands import resolve_child

    svc = AsyncMock()
    m1, m2 = MagicMock(), MagicMock()
    for m, uid, name in [(m1, 'uid-1', 'Emma'), (m2, 'uid-2', 'Tom')]:
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
    member.user_id = 'uid-1'
    member.profile.display_name = 'Emma'
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    result = await resolve_child(svc, 'uid-1')
    assert result == ('uid-1', 'Emma')


async def test_app_autocomplete_matches_title_case_insensitive():
    """Test that app_autocomplete finds an app by partial, case-insensitive title."""
    from familylink_server.bot.commands import app_autocomplete

    svc = AsyncMock()
    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    viber = MagicMock(title='Viber', package_name='com.viber.voip')
    tiktok = MagicMock(title='TikTok', package_name='com.zhiliaoapp.musically')
    svc.get_apps_and_usage.return_value = MagicMock(apps=[viber, tiktok])

    interaction = MagicMock(spec=discord.Interaction)
    interaction.namespace = MagicMock(child=None)

    with mock.patch(
        'familylink_server.services.family_link.get_service', return_value=svc
    ):
        choices = await app_autocomplete(interaction, 'vib')

    assert len(choices) == 1
    assert choices[0].value == 'com.viber.voip'


async def test_apps_block_calls_service():
    """Test that /apps block calls block_app on the service."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier, make_session=MagicMock())

    # Single child, no child_id needed
    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(['Parent'])
    await group.block.callback(group, interaction, package='com.tiktok', child='uid-1')

    svc.block_app.assert_awaited_once_with('com.tiktok', child_id='uid-1')
    interaction.response.send_message.assert_awaited_once()


async def test_apps_limit_calls_service():
    """Test that /apps limit calls set_app_limit on the service."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier, make_session=MagicMock())

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(['Parent'])
    await group.limit.callback(
        group, interaction, package='com.youtube', minutes=60, child='uid-1'
    )

    svc.set_app_limit.assert_awaited_once_with('com.youtube', 60, child_id='uid-1')


async def test_apps_allow_calls_service():
    """Test that /apps allow calls always_allow_app on the service."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier, make_session=MagicMock())

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(['Parent'])
    await group.allow.callback(group, interaction, package='com.youtube', child='uid-1')

    svc.always_allow_app.assert_awaited_once_with('com.youtube', child_id='uid-1')


async def test_apps_block_unauthorized():
    """Test that /apps block is rejected when the caller lacks the required role."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier, make_session=MagicMock())

    interaction = _make_interaction(['Member'])
    await group.block.callback(group, interaction, package='com.tiktok', child='uid-1')

    svc.block_app.assert_not_awaited()
    msg = interaction.response.send_message.call_args.kwargs
    assert msg.get('ephemeral') is True


async def test_devices_lock_calls_service():
    """Test that /devices lock calls lock_device on the service."""
    from familylink_server.bot.commands.devices import DevicesGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = DevicesGroup(svc, notifier)

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(['Parent'])
    await group.lock.callback(group, interaction, device='d-1', child='uid-1')

    svc.lock_device.assert_awaited_once_with('d-1', child_id='uid-1')
    interaction.response.send_message.assert_awaited_once()


async def test_devices_unlock_calls_service():
    """Test that /devices unlock calls unlock_device on the service."""
    from familylink_server.bot.commands.devices import DevicesGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = DevicesGroup(svc, notifier)

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(['Parent'])
    await group.unlock.callback(group, interaction, device='d-1', child='uid-1')

    svc.unlock_device.assert_awaited_once_with('d-1', child_id='uid-1')


async def test_usage_today_calls_service():
    """Test that /usage today calls get_apps_and_usage and sends a message."""
    from familylink_server.bot.commands.usage import UsageGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    group = UsageGroup(svc, notifier)

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    app_mock = MagicMock()
    app_mock.title = 'YouTube'
    app_mock.usage_today_seconds = 3600
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app_mock])

    interaction = _make_interaction(['Parent'])
    await group.today.callback(group, interaction, child='uid-1')

    svc.get_apps_and_usage.assert_awaited_once_with('uid-1')
    interaction.response.send_message.assert_awaited_once()


async def test_status_calls_service():
    """Test that /status calls get_members and sends an embed."""
    from contextlib import asynccontextmanager

    from familylink_server.bot.commands.usage import make_status_command

    svc = AsyncMock()

    # Dummy make_session that returns no machines
    @asynccontextmanager
    async def _dummy_make_session():
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result)
        yield session

    cmd = make_status_command(svc, _dummy_make_session)

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])
    svc.get_apps_and_usage.return_value = MagicMock(apps=[], device_info=[])

    interaction = _make_interaction(['Parent'])
    await cmd.callback(interaction)

    interaction.response.send_message.assert_awaited_once()


async def test_refresh_clears_cache():
    """Test that /refresh sets _members_cache to None and empties _usage_cache."""
    from familylink_server.bot.commands.usage import make_refresh_command

    svc = AsyncMock()
    svc._members_cache = object()
    svc._usage_cache = {'uid-1': object()}
    cmd = make_refresh_command(svc)

    interaction = _make_interaction(['Parent'])
    await cmd.callback(interaction)

    assert svc._members_cache is None
    assert svc._usage_cache == {}
    interaction.response.send_message.assert_awaited_once()


def _make_session_ctx(config=None):
    from unittest.mock import AsyncMock

    mock_session = AsyncMock()
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = config
    mock_exec_result.scalar_one.return_value = config
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx, mock_session


async def test_apps_auto_block_enables_when_app_has_limit():
    """'/apps auto-block' sets auto_block_enabled=True when the app has a Google limit."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    app = MagicMock()
    app.package_name = 'com.tiktok'
    app.supervision_setting.usage_limit = MagicMock(daily_usage_limit_mins=60)
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app])

    config = MagicMock()
    config.auto_block_enabled = False
    mock_ctx, mock_session = _make_session_ctx(config=config)
    make_session = MagicMock(return_value=mock_ctx)

    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.auto_block.callback(
        group, interaction, package='com.tiktok', enabled=True, child='uid-1'
    )

    assert config.auto_block_enabled is True
    mock_session.commit.assert_awaited_once()
    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.call_args[0][0]
    assert 'enabled' in msg.lower()
    assert 'com.tiktok' in msg


async def test_apps_auto_block_rejects_app_without_limit():
    """'/apps auto-block' refuses to enable when the app has no Google-side limit."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    app = MagicMock()
    app.package_name = 'com.tiktok'
    app.supervision_setting.usage_limit = None
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app])

    make_session = MagicMock()
    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.auto_block.callback(
        group, interaction, package='com.tiktok', enabled=True, child='uid-1'
    )

    make_session.assert_not_called()
    msg = interaction.response.send_message.call_args[0][0]
    assert 'no active' in msg.lower()


async def test_apps_auto_block_requires_role():
    """'/apps auto-block' replies with permission error without the Discord role."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    make_session = MagicMock()
    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction([])

    await group.auto_block.callback(
        group, interaction, package='com.tiktok', enabled=True, child='uid-1'
    )

    msg = interaction.response.send_message.call_args[0][0]
    assert 'permission' in msg.lower() or 'insufficient' in msg.lower()


async def test_apps_auto_block_disables_without_limit_check():
    """'/apps auto-block enabled=False' does not require an active Google-side limit."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    app = MagicMock()
    app.package_name = 'com.tiktok'
    app.supervision_setting.usage_limit = None
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app])

    config = MagicMock()
    config.auto_block_enabled = True
    mock_ctx, mock_session = _make_session_ctx(config=config)
    make_session = MagicMock(return_value=mock_ctx)

    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.auto_block.callback(
        group, interaction, package='com.tiktok', enabled=False, child='uid-1'
    )

    assert config.auto_block_enabled is False
    mock_session.commit.assert_awaited_once()
    msg = interaction.response.send_message.call_args[0][0]
    assert 'no active' not in msg.lower()


async def test_apps_bonus_stacks_same_day():
    """'/apps bonus' adds to existing same-day bonus_mins."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    from datetime import date

    app = MagicMock()
    app.package_name = 'com.tiktok'
    app.supervision_setting.usage_limit = MagicMock(daily_usage_limit_mins=60)
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app])

    config = MagicMock()
    config.bonus_mins = 15
    config.bonus_date = date.today()
    config.auto_blocked_at = None
    mock_ctx, mock_session = _make_session_ctx(config=config)
    make_session = MagicMock(return_value=mock_ctx)

    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.bonus.callback(
        group, interaction, package='com.tiktok', minutes=30, child='uid-1'
    )

    assert config.bonus_mins == 45
    svc.set_app_limit.assert_not_called()
    msg = interaction.response.send_message.call_args[0][0]
    assert '+30' in msg
    assert '45 min bonus today' in msg


async def test_apps_bonus_resets_on_new_day():
    """'/apps bonus' resets bonus_mins when bonus_date is not today."""
    from datetime import date

    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    app = MagicMock()
    app.package_name = 'com.tiktok'
    app.supervision_setting.usage_limit = MagicMock(daily_usage_limit_mins=60)
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app])

    config = MagicMock()
    config.bonus_mins = 999
    config.bonus_date = date(2000, 1, 1)
    config.auto_blocked_at = None
    mock_ctx, mock_session = _make_session_ctx(config=config)
    make_session = MagicMock(return_value=mock_ctx)

    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.bonus.callback(
        group, interaction, package='com.tiktok', minutes=15, child='uid-1'
    )

    assert config.bonus_mins == 15


async def test_apps_bonus_unblocks_when_auto_blocked():
    """'/apps bonus' calls set_app_limit and clears auto_blocked_at when currently blocked."""
    from datetime import UTC, date, datetime

    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    app = MagicMock()
    app.package_name = 'com.tiktok'
    app.supervision_setting.usage_limit = MagicMock(daily_usage_limit_mins=60)
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app])

    config = MagicMock()
    config.bonus_mins = 0
    config.bonus_date = date.today()
    config.auto_blocked_at = datetime.now(UTC)
    mock_ctx, mock_session = _make_session_ctx(config=config)
    make_session = MagicMock(return_value=mock_ctx)

    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.bonus.callback(
        group, interaction, package='com.tiktok', minutes=30, child='uid-1'
    )

    svc.set_app_limit.assert_awaited_once_with('com.tiktok', 60, child_id='uid-1')
    assert config.auto_blocked_at is None
    msg = interaction.response.send_message.call_args[0][0]
    assert 'unblocked' in msg.lower()


async def test_apps_bonus_requires_role():
    """'/apps bonus' replies with permission error without the Discord role."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    make_session = MagicMock()
    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction([])

    await group.bonus.callback(
        group, interaction, package='com.tiktok', minutes=15, child='uid-1'
    )

    msg = interaction.response.send_message.call_args[0][0]
    assert 'permission' in msg.lower() or 'insufficient' in msg.lower()
