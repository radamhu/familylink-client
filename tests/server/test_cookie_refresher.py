"""Tests for the cookie-refresher sidecar app."""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_bootstrap_writes_state_file(monkeypatch, tmp_path):
    """POST /bootstrap writes the storage_state JSON to STATE_PATH."""
    state_file = tmp_path / 'state.json'
    monkeypatch.setenv('STATE_PATH', str(state_file))
    from familylink_server.cookie_refresher_app import app

    client = TestClient(app)
    resp = client.post(
        '/bootstrap',
        json={
            'cookies': [
                {
                    'name': 'SAPISID',
                    'value': 'abc',
                    'domain': '.google.com',
                    'path': '/',
                    'expires': -1,
                    'httpOnly': False,
                    'secure': True,
                    'sameSite': 'None',
                }
            ],
            'origins': [],
        },
    )
    assert resp.status_code == 204

    saved = json.loads(state_file.read_text())
    assert saved['cookies'][0]['name'] == 'SAPISID'
    assert saved['origins'] == []


def test_bootstrap_forbidden_when_wrong_key(monkeypatch, tmp_path):
    """POST /bootstrap returns 403 when REFRESHER_API_KEY is set and key is wrong."""
    monkeypatch.setenv('REFRESHER_API_KEY', 'secret')
    monkeypatch.setenv('STATE_PATH', str(tmp_path / 'state.json'))
    from familylink_server.cookie_refresher_app import app

    client = TestClient(app)
    resp = client.post(
        '/bootstrap',
        json={'cookies': [], 'origins': []},
        headers={'X-Api-Key': 'wrong'},
    )
    assert resp.status_code == 403


def test_to_netscape_subdomain_flag():
    """Domains starting with '.' should use TRUE for include_subdomains."""
    from familylink_server.cookie_refresher_app import _to_netscape

    cookies = [
        {
            'name': 'SAPISID',
            'value': 'abc/def',
            'domain': '.google.com',
            'path': '/',
            'expires': 1234567890.0,
            'secure': True,
        }
    ]
    result = _to_netscape(cookies)
    assert result.startswith('# Netscape HTTP Cookie File\n')
    assert '.google.com\tTRUE\t/\tTRUE\t1234567890\tSAPISID\tabc/def' in result


def test_to_netscape_non_subdomain():
    """Domains not starting with '.' should use FALSE for include_subdomains."""
    from familylink_server.cookie_refresher_app import _to_netscape

    cookies = [
        {
            'name': 'SESSION',
            'value': 'xyz',
            'domain': 'accounts.google.com',
            'path': '/',
            'expires': 0,
            'secure': False,
        }
    ]
    result = _to_netscape(cookies)
    assert 'accounts.google.com\tFALSE\t/\tFALSE\t0\tSESSION\txyz' in result


def test_to_netscape_missing_expires():
    """Cookies without 'expires' key should default to expiry 0."""
    from familylink_server.cookie_refresher_app import _to_netscape

    cookies = [
        {'name': 'X', 'value': 'y', 'domain': '.g.com', 'path': '/', 'secure': False}
    ]
    result = _to_netscape(cookies)
    assert '\t0\tX\ty' in result


def test_health_endpoint():
    """GET /health should return 200 with status ok."""
    from familylink_server.cookie_refresher_app import app

    client = TestClient(app)
    resp = client.get('/health')
    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok'}


def test_refresh_missing_state(monkeypatch, tmp_path):
    """POST /refresh returns 500 with a clear message when no state file exists."""
    monkeypatch.setenv('STATE_PATH', str(tmp_path / 'missing.json'))
    from familylink_server.cookie_refresher_app import app

    client = TestClient(app)
    resp = client.post('/refresh')
    assert resp.status_code == 500
    assert 'run bootstrap first' in resp.json()['detail']


def test_get_cookies_b64_raises_when_expired(monkeypatch, tmp_path):
    """_get_cookies_b64 raises RuntimeError when navigation produces no SAPISID cookie."""
    import sys
    import types

    state_path = tmp_path / 'state.json'
    state_path.write_text('{"cookies": [], "origins": []}')

    consent_only = [
        {
            'domain': '.google.com',
            'path': '/',
            'name': 'NID',
            'value': 'x',
            'secure': True,
            'expires': 9999999999,
        },
    ]

    class FakePage:
        url = 'https://myaccount.google.com/'

        def goto(self, *a, **kw):
            pass

        def title(self):
            return 'My Account'

    class FakeContext:
        def add_init_script(self, *a, **kw):
            pass

        def new_page(self):
            return FakePage()

        def cookies(self):
            return consent_only

        def storage_state(self, path=None):
            return {'cookies': consent_only, 'origins': []}

    class FakeBrowser:
        def new_context(self, **kw):
            return FakeContext()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **kw):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    fake_sync_api = types.ModuleType('playwright.sync_api')
    fake_sync_api.sync_playwright = lambda: FakePlaywright()

    fake_playwright_pkg = types.ModuleType('playwright')
    fake_playwright_pkg.sync_api = fake_sync_api

    monkeypatch.setitem(sys.modules, 'playwright', fake_playwright_pkg)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', fake_sync_api)

    import pytest

    from familylink_server.cookie_refresher_app import _get_cookies_b64

    with pytest.raises(RuntimeError, match='expired'):
        _get_cookies_b64(state_path)


def test_get_cookies_b64_includes_page_context_on_failure(monkeypatch, tmp_path):
    """_get_cookies_b64 error message includes page URL/title when navigation fails."""
    import sys
    import types

    state_path = tmp_path / 'state.json'
    state_path.write_text('{"cookies": [], "origins": []}')

    class FakePage:
        url = 'https://accounts.google.com/v3/signin/challenge/az'

        def goto(self, *a, **kw):
            raise TimeoutError('Timeout 30000ms exceeded waiting for navigation')

        def title(self):
            return "Couldn't sign you in"

    class FakeContext:
        def add_init_script(self, *a, **kw):
            pass

        def new_page(self):
            return FakePage()

        def cookies(self):
            return []

        def storage_state(self, path=None):
            return {'cookies': [], 'origins': []}

    class FakeBrowser:
        def new_context(self, **kw):
            return FakeContext()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **kw):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    fake_sync_api = types.ModuleType('playwright.sync_api')
    fake_sync_api.sync_playwright = lambda: FakePlaywright()

    fake_playwright_pkg = types.ModuleType('playwright')
    fake_playwright_pkg.sync_api = fake_sync_api

    monkeypatch.setitem(sys.modules, 'playwright', fake_playwright_pkg)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', fake_sync_api)

    import pytest

    from familylink_server.cookie_refresher_app import _get_cookies_b64

    with pytest.raises(RuntimeError) as exc_info:
        _get_cookies_b64(state_path)

    message = str(exc_info.value)
    assert 'accounts.google.com/v3/signin/challenge/az' in message
    assert "Couldn't sign you in" in message


def test_get_cookies_b64_writes_rotated_state(monkeypatch, tmp_path):
    """_get_cookies_b64 loads from and persists back to the same state file."""
    import sys
    import types

    state_path = tmp_path / 'state.json'
    state_path.write_text('{"cookies": [], "origins": []}')

    fresh_cookies = [
        {
            'domain': '.google.com',
            'path': '/',
            'name': 'SAPISID',
            'value': 'y',
            'secure': True,
            'expires': 9999999999,
        },
    ]

    written = {}

    class FakePage:
        url = 'https://myaccount.google.com/'

        def goto(self, *a, **kw):
            pass

    class FakeContext:
        def add_init_script(self, *a, **kw):
            pass

        def new_page(self):
            return FakePage()

        def cookies(self):
            return fresh_cookies

        def storage_state(self, path=None):
            written['path'] = path
            return {'cookies': fresh_cookies, 'origins': []}

    class FakeBrowser:
        def new_context(self, **kw):
            written['loaded_from'] = kw.get('storage_state')
            return FakeContext()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **kw):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    fake_sync_api = types.ModuleType('playwright.sync_api')
    fake_sync_api.sync_playwright = lambda: FakePlaywright()

    fake_playwright_pkg = types.ModuleType('playwright')
    fake_playwright_pkg.sync_api = fake_sync_api

    monkeypatch.setitem(sys.modules, 'playwright', fake_playwright_pkg)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', fake_sync_api)

    from familylink_server.cookie_refresher_app import _get_cookies_b64

    with patch('familylink_server.cookie_refresher_app._verify_family_link_access'):
        result = _get_cookies_b64(state_path)

    assert written['loaded_from'] == str(state_path)
    assert written['path'] == str(state_path)

    import base64

    assert base64.b64decode(result).decode().count('SAPISID') == 1


def test_refresh_success(monkeypatch):
    """POST /refresh should return cookies_b64 when _get_cookies_b64 succeeds."""
    with patch(
        'familylink_server.cookie_refresher_app._get_cookies_b64',
        return_value='dGVzdA==',
    ):
        from familylink_server.cookie_refresher_app import app

        client = TestClient(app)
        resp = client.post('/refresh')

    assert resp.status_code == 200
    assert resp.json() == {'cookies_b64': 'dGVzdA=='}


def test_refresh_playwright_error(monkeypatch):
    """POST /refresh should return 500 when Playwright login fails."""
    with patch(
        'familylink_server.cookie_refresher_app._get_cookies_b64',
        side_effect=RuntimeError('CAPTCHA detected'),
    ):
        from familylink_server.cookie_refresher_app import app

        client = TestClient(app)
        resp = client.post('/refresh')

    assert resp.status_code == 500
    assert 'CAPTCHA' in resp.json()['detail']


def test_refresh_forbidden_when_wrong_key(monkeypatch):
    """POST /refresh returns 403 when REFRESHER_API_KEY is set and key is wrong."""
    from fastapi.testclient import TestClient

    from familylink_server.cookie_refresher_app import app as refresher_app

    monkeypatch.setenv('REFRESHER_API_KEY', 'secret')

    client = TestClient(refresher_app)
    resp = client.post('/refresh', headers={'X-Api-Key': 'wrong'})
    assert resp.status_code == 403


def test_refresh_allowed_when_key_matches(monkeypatch):
    """POST /refresh returns 200 when correct X-Api-Key header is sent."""
    from fastapi.testclient import TestClient

    from familylink_server.cookie_refresher_app import app as refresher_app

    monkeypatch.setenv('REFRESHER_API_KEY', 'secret')

    with patch(
        'familylink_server.cookie_refresher_app._get_cookies_b64',
        return_value='dGVzdA==',
    ):
        client = TestClient(refresher_app)
        resp = client.post('/refresh', headers={'X-Api-Key': 'secret'})
    assert resp.status_code == 200
    assert resp.json()['cookies_b64'] == 'dGVzdA=='
