"""Tests for FamilyLinkBot's scheduled daily summary retry behavior."""

import os

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://localhost/familylink_test')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-32-bytes-exactly!')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'test-client-id')
os.environ.setdefault('GOOGLE_CLIENT_SECRET', 'test-client-secret')
os.environ.setdefault('FAMILYLINK_GOOGLE_EMAIL', 'parent@gmail.com')
os.environ.setdefault('FAMILYLINK_COOKIES_B64', 'dGVzdA==')

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

from familylink_server.bot import client as client_module
from familylink_server.bot.client import FamilyLinkBot


def _make_bot(service: AsyncMock, notifier: AsyncMock) -> FamilyLinkBot:
    return FamilyLinkBot(
        service=service,
        notifier=notifier,
        guild_id=123,
        summary_time=dt.time(20, 0, tzinfo=dt.UTC),
        make_session=MagicMock(),
    )


async def test_run_daily_summary_retries_after_transient_failure(monkeypatch):
    """A single transient get_members() failure is retried, not silently dropped."""
    sleeps = []
    monkeypatch.setattr(
        client_module.asyncio,
        'sleep',
        AsyncMock(side_effect=lambda s: sleeps.append(s)),
    )

    service = AsyncMock()
    service.get_members.side_effect = [
        Exception('401 session expired'),
        MagicMock(members=[]),
    ]
    notifier = AsyncMock()
    bot = _make_bot(service, notifier)

    await bot._run_daily_summary()

    assert service.get_members.call_count == 2
    assert len(sleeps) == 1


async def test_run_daily_summary_gives_up_after_max_attempts(monkeypatch):
    """After exhausting retries, the failure is logged and swallowed (no crash)."""
    monkeypatch.setattr(client_module.asyncio, 'sleep', AsyncMock())

    service = AsyncMock()
    service.get_members.side_effect = Exception('401 session expired')
    notifier = AsyncMock()
    bot = _make_bot(service, notifier)

    await bot._run_daily_summary()

    assert service.get_members.call_count == client_module.DAILY_SUMMARY_MAX_ATTEMPTS
    notifier.post_daily_summary.assert_not_called()


async def test_run_daily_summary_no_retry_on_first_attempt_success(monkeypatch):
    """When the first attempt succeeds, no sleep/retry happens at all."""
    sleep_mock = AsyncMock()
    monkeypatch.setattr(client_module.asyncio, 'sleep', sleep_mock)

    service = AsyncMock()
    service.get_members.return_value = MagicMock(members=[])
    notifier = AsyncMock()
    bot = _make_bot(service, notifier)

    await bot._run_daily_summary()

    assert service.get_members.call_count == 1
    sleep_mock.assert_not_called()
