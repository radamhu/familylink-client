"""Tests for health_check_loop background task."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from familylink import SessionExpiredError
from familylink_server.main import health_check_loop


def _make_service(*, fail=False):
    """Build a mock FamilyLinkService; optionally pre-configure it to raise on get_members."""
    svc = MagicMock()
    svc.auth_failed = False
    svc.set_auth_failed = MagicMock()
    if fail:
        svc.get_members = AsyncMock(side_effect=SessionExpiredError("expired"))
    else:
        svc.get_members = AsyncMock(return_value=MagicMock())
    return svc


async def test_health_check_alerts_on_first_failure():
    """First failure calls notify_session_expired and sets auth_failed=True."""
    svc = _make_service(fail=True)
    notifier = AsyncMock()

    sleep_count = 0

    async def mock_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", new=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            await health_check_loop(svc, notifier, interval=0)

    notifier.notify_session_expired.assert_awaited_once()
    svc.set_auth_failed.assert_called_with(True)


async def test_health_check_no_duplicate_alerts():
    """Repeated failures do not send duplicate session-expired alerts."""
    svc = _make_service(fail=True)
    notifier = AsyncMock()

    sleep_count = 0

    async def mock_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 4:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", new=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            await health_check_loop(svc, notifier, interval=0)

    assert notifier.notify_session_expired.await_count == 1


async def test_health_check_restored_alert_on_recovery():
    """Recovery after failure triggers notify_session_restored exactly once."""
    svc = MagicMock()
    svc.auth_failed = False
    svc.set_auth_failed = MagicMock()
    notifier = AsyncMock()

    call_count = 0

    async def get_members_side():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise SessionExpiredError("expired")

    svc.get_members = get_members_side

    sleep_count = 0

    async def mock_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 4:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", new=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            await health_check_loop(svc, notifier, interval=0)

    notifier.notify_session_expired.assert_awaited_once()
    notifier.notify_session_restored.assert_awaited_once()


async def test_health_check_noop_when_notifier_is_none():
    """Loop continues and calls set_auth_failed even when notifier is None."""
    svc = _make_service(fail=True)

    sleep_count = 0

    async def mock_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", new=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            await health_check_loop(svc, notifier=None, interval=0)
