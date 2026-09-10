"""Tests for NtfyNotifier service."""

from unittest.mock import AsyncMock

import pytest

TEST_BASE_URL = 'http://ntfy-qs0o4os08kggkcgs4kos4sgk.192.168.0.22.sslip.io'


@pytest.fixture()
def notifier():
    """Create a test notifier with one mapped kid."""
    from familylink_server.services.ntfy_notifier import NtfyNotifier

    return NtfyNotifier(
        topics={'child1': 'familylink-child1-abc123'}, base_url=TEST_BASE_URL
    )


async def test_send_no_op_for_unmapped_child(notifier, httpx_mock):
    """No topic mapped for this child_id -> no HTTP call is made."""
    await notifier.send('child-unknown', 'Title', 'Message')
    assert len(httpx_mock.get_requests()) == 0


async def test_send_posts_json_payload_to_ntfy(notifier, httpx_mock):
    httpx_mock.add_response(url=TEST_BASE_URL, method='POST')
    await notifier.send('child1', 'Hello', 'World', priority='high', tags=['book'])

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    body = requests[0].read()
    import json

    payload = json.loads(body)
    assert payload == {
        'topic': 'familylink-child1-abc123',
        'title': 'Hello',
        'message': 'World',
        'priority': 'high',
        'tags': ['book'],
    }


async def test_send_swallows_http_errors(notifier, httpx_mock):
    """A failed ntfy push must not raise — it's best-effort."""
    httpx_mock.add_response(url=TEST_BASE_URL, method='POST', status_code=500)
    await notifier.send('child1', 'Hello', 'World')  # must not raise


async def test_notify_homework_calls_send_with_expected_args(notifier):
    notifier.send = AsyncMock()
    await notifier.notify_homework('child1', 'Matek', '2026-09-15')
    notifier.send.assert_awaited_once_with(
        'child1',
        title='📚 New homework — Matek',
        message='Due 2026-09-15',
        tags=['book'],
    )


async def test_notify_low_time_calls_send_with_expected_args(notifier):
    notifier.send = AsyncMock()
    await notifier.notify_low_time('child1', 'TikTok', 12)
    notifier.send.assert_awaited_once_with(
        'child1',
        title='⏰ TikTok: 12 min left',
        message='TikTok will lock soon — 12 minutes remaining today.',
        priority='high',
        tags=['hourglass'],
    )


def test_init_notifier_sets_singleton():
    """init_notifier should create and return the singleton."""
    from familylink_server.services import ntfy_notifier as mod

    mod._notifier = None
    notifier = mod.init_notifier({'child1': 'topic1'}, base_url=TEST_BASE_URL)
    assert mod.get_notifier() is notifier
    assert notifier._topics == {'child1': 'topic1'}
    assert notifier._base_url == TEST_BASE_URL
    mod._notifier = None  # cleanup
