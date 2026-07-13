"""Tests for the app-overuse enforcer."""

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_config(
    package_name='com.example.app',
    auto_blocked_at=None,
    bonus_mins=0,
    bonus_date=None,
):
    cfg = MagicMock()
    cfg.package_name = package_name
    cfg.auto_blocked_at = auto_blocked_at
    cfg.bonus_mins = bonus_mins
    cfg.bonus_date = bonus_date
    return cfg


def _make_app(package_name='com.example.app', limit_mins=30):
    app = MagicMock()
    app.package_name = package_name
    app.supervision_setting.usage_limit = (
        MagicMock(daily_usage_limit_mins=limit_mins) if limit_mins is not None else None
    )
    return app


def _make_usage_session(
    package_name='com.example.app', usage_seconds=0.0, day_offset=0
):
    d = datetime.date.today() + datetime.timedelta(days=day_offset)
    s = MagicMock()
    s.usage = str(usage_seconds)
    s.app_id.android_app_package_name = package_name
    s.date.year = d.year
    s.date.month = d.month
    s.date.day = d.day
    return s


def _make_usage(apps, sessions):
    u = MagicMock()
    u.apps = apps
    u.app_usage_sessions = sessions
    return u


def _make_session_ctx(configs):
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = configs
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx, mock_session


async def test_enforce_child_blocks_when_usage_exceeds_limit():
    """usage_mins >= limit and not yet blocked -> block_app is called and auto_blocked_at is set."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config()
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=30 * 60)],
    )
    mock_ctx, mock_session = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_awaited_once_with('com.example.app', 'child1')
    assert config.auto_blocked_at is not None
    mock_session.commit.assert_awaited_once()


async def test_enforce_child_does_not_block_when_under_limit():
    """usage_mins < limit -> block_app is not called."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config()
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=10 * 60)],
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_not_awaited()
    assert config.auto_blocked_at is None


async def test_enforce_child_skips_when_no_google_limit():
    """App has no usage_limit configured in Google -> nothing happens."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config()
    usage = _make_usage(
        [_make_app(limit_mins=None)],
        [_make_usage_session(usage_seconds=999 * 60)],
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_not_awaited()


async def test_enforce_child_restores_after_midnight():
    """auto_blocked_at from a previous day -> set_app_limit restores, auto_blocked_at clears."""
    from familylink_server.services.app_enforcer import enforce_child

    yesterday = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    config = _make_config(auto_blocked_at=yesterday)
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=0)],
    )
    mock_ctx, mock_session = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.set_app_limit = AsyncMock()
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.set_app_limit.assert_awaited_once_with('com.example.app', 30, 'child1')
    assert config.auto_blocked_at is None
    mock_svc.block_app.assert_not_awaited()
    mock_session.commit.assert_awaited_once()


async def test_enforce_child_idempotent_when_already_blocked_today():
    """auto_blocked_at set today, still over limit -> block_app is not called again."""
    from familylink_server.services.app_enforcer import enforce_child

    now = datetime.datetime.now(datetime.UTC)
    config = _make_config(auto_blocked_at=now)
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=45 * 60)],
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_not_awaited()


async def test_enforce_child_bonus_raises_effective_limit():
    """bonus_mins granted today keeps the app unblocked past the base limit."""
    from familylink_server.services.app_enforcer import enforce_child

    today = datetime.date.today()
    config = _make_config(bonus_mins=15, bonus_date=today)
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [
            _make_usage_session(usage_seconds=40 * 60)
        ],  # 40 min: over base 30, under 30+15
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_not_awaited()


async def test_enforce_child_reblocks_after_bonus_exceeded():
    """Usage crosses base limit + bonus -> block_app is called using the raised threshold."""
    from familylink_server.services.app_enforcer import enforce_child

    today = datetime.date.today()
    config = _make_config(bonus_mins=15, bonus_date=today)
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=45 * 60)],  # 45 min >= 30+15
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_awaited_once_with('com.example.app', 'child1')
    assert config.auto_blocked_at is not None


async def test_enforce_child_sums_multiple_sessions_same_day_ignores_other_days():
    """Usage from two devices today is summed; a session from a different day is ignored."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config()
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [
            _make_usage_session(usage_seconds=10 * 60),
            _make_usage_session(usage_seconds=25 * 60),
            _make_usage_session(usage_seconds=999 * 60, day_offset=-1),
        ],
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    # 10 + 25 = 35 min >= 30 min limit -> blocks; the 999-min session from yesterday is excluded
    mock_svc.block_app.assert_awaited_once_with('com.example.app', 'child1')


async def test_app_enforcer_loop_calls_enforce_child_for_each_distinct_child():
    """The loop queries distinct opted-in child_ids and enforces each one."""
    from familylink_server.services import app_enforcer

    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = ['child1', 'child2']
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_enforce = AsyncMock()
    mock_svc = MagicMock()

    async def _raise_cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    with (
        patch(
            'familylink_server.services.app_enforcer.make_session',
            return_value=mock_ctx,
        ),
        patch('familylink_server.services.app_enforcer.enforce_child', mock_enforce),
        patch(
            'familylink_server.services.app_enforcer.asyncio.sleep',
            side_effect=_raise_cancelled,
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await app_enforcer.app_enforcer_loop(mock_svc)

    mock_enforce.assert_any_await('child1', mock_svc, notifier=None)
    mock_enforce.assert_any_await('child2', mock_svc, notifier=None)
