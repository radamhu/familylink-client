"""Tests for the cookie-refresher sidecar app."""

from unittest.mock import patch

from fastapi.testclient import TestClient


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


def test_refresh_missing_password(monkeypatch):
    """POST /refresh should return 400 when FAMILYLINK_GOOGLE_PASSWORD is unset."""
    monkeypatch.delenv('FAMILYLINK_GOOGLE_PASSWORD', raising=False)
    monkeypatch.setenv('FAMILYLINK_GOOGLE_EMAIL', 'test@gmail.com')
    monkeypatch.setenv('FAMILYLINK_TOTP_SECRET', 'JBSWY3DPEHPK3PXP')
    from familylink_server.cookie_refresher_app import app

    client = TestClient(app)
    resp = client.post('/refresh')
    assert resp.status_code == 400
    assert 'FAMILYLINK_GOOGLE_PASSWORD' in resp.json()['detail']


def test_refresh_missing_totp(monkeypatch):
    """POST /refresh should return 400 when FAMILYLINK_TOTP_SECRET is unset."""
    monkeypatch.setenv('FAMILYLINK_GOOGLE_EMAIL', 'test@gmail.com')
    monkeypatch.setenv('FAMILYLINK_GOOGLE_PASSWORD', 'secret')
    monkeypatch.delenv('FAMILYLINK_TOTP_SECRET', raising=False)
    from familylink_server.cookie_refresher_app import app

    client = TestClient(app)
    resp = client.post('/refresh')
    assert resp.status_code == 400


def test_refresh_success(monkeypatch):
    """POST /refresh should return cookies_b64 when _get_cookies_b64 succeeds."""
    monkeypatch.setenv('FAMILYLINK_GOOGLE_EMAIL', 'test@gmail.com')
    monkeypatch.setenv('FAMILYLINK_GOOGLE_PASSWORD', 'secret')
    monkeypatch.setenv('FAMILYLINK_TOTP_SECRET', 'JBSWY3DPEHPK3PXP')

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
    monkeypatch.setenv('FAMILYLINK_GOOGLE_EMAIL', 'test@gmail.com')
    monkeypatch.setenv('FAMILYLINK_GOOGLE_PASSWORD', 'secret')
    monkeypatch.setenv('FAMILYLINK_TOTP_SECRET', 'JBSWY3DPEHPK3PXP')

    with patch(
        'familylink_server.cookie_refresher_app._get_cookies_b64',
        side_effect=RuntimeError('CAPTCHA detected'),
    ):
        from familylink_server.cookie_refresher_app import app

        client = TestClient(app)
        resp = client.post('/refresh')

    assert resp.status_code == 500
    assert 'CAPTCHA' in resp.json()['detail']
