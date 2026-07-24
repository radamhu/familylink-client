"""Tests for auto-refresh via sidecar."""

import asyncio  # noqa: F401
import os
from unittest.mock import MagicMock, patch

import familylink_server.main as main
from familylink_server.services.family_link import FamilyLinkService


def _make_service():
    """Create FamilyLinkService bypassing __init__."""
    svc = FamilyLinkService.__new__(FamilyLinkService)
    svc._ttl = 0
    svc._members_cache = None
    svc._usage_cache = {}
    svc._auth_failed = False
    svc._client = MagicMock()
    return svc


def test_cookie_refresher_url_default():
    """cookie_refresher_url should default to empty string."""
    from familylink_server.config import settings

    assert settings.cookie_refresher_url == ''


def test_reinit_with_cookies_b64_sets_env():
    """reinit_with_cookies_b64 should set FAMILYLINK_COOKIES_B64 in os.environ."""
    svc = _make_service()
    with patch('familylink_server.services.family_link.FamilyLink'):
        with patch.dict(os.environ, {}, clear=False):
            svc.reinit_with_cookies_b64('new_b64_value')
            assert os.environ.get('FAMILYLINK_COOKIES_B64') == 'new_b64_value'


def test_reinit_with_cookies_b64_pops_sapisid():
    """reinit_with_cookies_b64 should remove FAMILYLINK_SAPISID from os.environ."""
    svc = _make_service()
    with patch('familylink_server.services.family_link.FamilyLink'):
        with patch.dict(os.environ, {'FAMILYLINK_SAPISID': 'old_sid'}, clear=False):
            svc.reinit_with_cookies_b64('new_b64_value')
            assert 'FAMILYLINK_SAPISID' not in os.environ


def test_reinit_with_cookies_b64_clears_caches():
    """reinit_with_cookies_b64 should clear caches but leave auth_failed for the caller to verify."""
    svc = _make_service()
    svc._members_cache = (MagicMock(), MagicMock())
    svc._usage_cache = {'child1': (MagicMock(), MagicMock())}
    svc._auth_failed = True

    with patch('familylink_server.services.family_link.FamilyLink'):
        svc.reinit_with_cookies_b64('abc')

    assert svc._members_cache is None
    assert svc._usage_cache == {}
    assert svc._auth_failed is True  # unverified — caller must confirm before clearing


def test_reinit_with_cookies_b64_creates_new_client():
    """reinit_with_cookies_b64 should replace _client with new FamilyLink instance."""
    svc = _make_service()
    old_client = svc._client

    with patch('familylink_server.services.family_link.FamilyLink') as MockFL:
        MockFL.return_value = MagicMock()
        svc.reinit_with_cookies_b64('abc')

    assert svc._client is not old_client
    MockFL.assert_called_once()


async def test_try_auto_refresh_no_op_when_url_not_set(monkeypatch):
    """_try_auto_refresh should return False immediately when COOKIE_REFRESHER_URL is empty."""
    from familylink_server.config import settings
    from familylink_server.main import _try_auto_refresh

    monkeypatch.setattr(settings, 'cookie_refresher_url', '')
    svc = _make_service()
    result = await _try_auto_refresh(svc, None)
    assert result is False
    assert svc._auth_failed is False  # untouched


async def test_try_auto_refresh_success(httpx_mock, monkeypatch):
    """_try_auto_refresh should call sidecar, reinit service, and return True on success."""
    from familylink_server.config import settings
    from familylink_server.main import _try_auto_refresh

    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://sidecar:8080')
    httpx_mock.add_response(
        url='http://sidecar:8080/refresh',
        method='POST',
        json={'cookies_b64': 'dGVzdA=='},
    )

    svc = _make_service()
    with patch('familylink_server.services.family_link.FamilyLink'):
        result = await _try_auto_refresh(svc, None)

    assert result is True
    assert os.environ.get('FAMILYLINK_COOKIES_B64') == 'dGVzdA=='
    assert svc._auth_failed is False


async def test_try_auto_refresh_returns_false_on_http_error(httpx_mock, monkeypatch):
    """_try_auto_refresh should return False when sidecar returns non-2xx."""
    from familylink_server.config import settings
    from familylink_server.main import _try_auto_refresh

    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://sidecar:8080')
    httpx_mock.add_response(
        url='http://sidecar:8080/refresh',
        method='POST',
        status_code=500,
        text='Playwright error',
    )

    svc = _make_service()
    result = await _try_auto_refresh(svc, None)
    assert result is False


async def test_try_auto_refresh_returns_false_on_network_error(monkeypatch):
    """_try_auto_refresh should return False on connection error without raising."""
    import httpx as _httpx

    from familylink_server.config import settings
    from familylink_server.main import _try_auto_refresh

    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://sidecar:8080')

    with patch('httpx.AsyncClient') as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = MagicMock(return_value=mock_client)
        mock_client.__aexit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(side_effect=_httpx.ConnectError('refused'))
        mock_client_cls.return_value = mock_client

        svc = _make_service()
        result = await _try_auto_refresh(svc, None)

    assert result is False


async def test_try_auto_refresh_skips_when_already_in_progress(monkeypatch):
    """A second _try_auto_refresh call while one is in-flight returns False immediately.

    Prevents health_check_loop and _kick_off_background_refresh from racing
    concurrent /refresh calls against the sidecar, which shares a single
    on-disk storage_state file.
    """
    from familylink_server.config import settings
    from familylink_server.main import _try_auto_refresh

    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://sidecar:8080')

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {'cookies_b64': 'dGVzdA=='}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            nonlocal call_count
            call_count += 1
            entered.set()
            await release.wait()
            return FakeResponse()

    svc1 = _make_service()
    svc2 = _make_service()

    with (
        patch('httpx.AsyncClient', return_value=FakeClient()),
        patch('familylink_server.services.family_link.FamilyLink'),
    ):
        task1 = asyncio.create_task(_try_auto_refresh(svc1, None))
        await entered.wait()  # first call is now mid-flight, holding the guard

        task2 = asyncio.create_task(_try_auto_refresh(svc2, None))
        result2 = await asyncio.wait_for(task2, timeout=0.2)

        release.set()
        result1 = await task1

    assert call_count == 1  # sidecar was only ever hit once concurrently
    assert result2 is False
    assert result1 is True


async def test_health_check_loop_resets_alert_on_auto_refresh_success(monkeypatch):
    """health_check_loop should reset _alert_active when auto-refresh succeeds."""
    from familylink import SessionExpiredError
    from familylink_server.config import settings
    from familylink_server.main import health_check_loop

    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://sidecar:8080')

    svc = _make_service()
    call_count = 0

    async def fake_get_members():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise SessionExpiredError('expired')
        # Second call succeeds

    svc.get_members = fake_get_members

    notified_expired = []
    notified_restored = []

    class FakeNotifier:
        async def notify_session_expired(self):
            notified_expired.append(True)

        async def notify_session_restored(self):
            notified_restored.append(True)

    sleep_calls = []

    async def fake_sleep(n):
        sleep_calls.append(n)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError  # stop the loop after 2 iterations

    async def mock_refresh_impl(service, notifier):
        service.reinit_with_cookies_b64('test_b64')
        service.set_auth_failed(False)
        return True

    with (
        patch('familylink_server.main.asyncio.sleep', side_effect=fake_sleep),
        patch(
            'familylink_server.main._try_auto_refresh', side_effect=mock_refresh_impl
        ) as mock_refresh,
        patch('familylink_server.services.family_link.FamilyLink'),
    ):
        try:
            await health_check_loop(svc, FakeNotifier(), interval=0)
        except asyncio.CancelledError:
            pass

    # Auto-refresh was called on first SessionExpiredError
    mock_refresh.assert_called_once()
    # auth_failed flag was set then cleared
    assert svc._auth_failed is False


async def test_backoff_skips_sidecar_after_failure(monkeypatch, httpx_mock):
    monkeypatch.setattr(main.settings, 'cookie_refresher_url', 'http://cr:8080')
    main._reset_refresh_backoff()
    httpx_mock.add_response(url='http://cr:8080/refresh', status_code=500)

    class _Svc:
        def set_auth_failed(self, v):
            pass

    ok1 = await main._try_auto_refresh(_Svc(), None)
    ok2 = await main._try_auto_refresh(_Svc(), None)  # immediately again

    assert ok1 is False and ok2 is False
    # sidecar hit only once; the second call was suppressed by backoff
    assert len(httpx_mock.get_requests()) == 1


async def test_proactive_loop_calls_refresh(monkeypatch):
    calls = []

    async def _fake_refresh(service, notifier):
        calls.append(True)
        return True

    monkeypatch.setattr(main, '_try_auto_refresh', _fake_refresh)
    task = asyncio.create_task(main.proactive_refresh_loop(object(), None, interval=0))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert calls, 'proactive loop should have called _try_auto_refresh at least once'
