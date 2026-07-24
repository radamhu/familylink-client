"""Tests for the live-profile cookie-refresher sidecar."""

import base64

from fastapi.testclient import TestClient


class _FakeCookie:
    def __init__(
        self, name, value='v', domain='.google.com', path='/', secure=True, expires=0
    ):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path
        self.secure = secure
        self.expires = expires


def _client(monkeypatch, tmp_path, jar, verify_ok=True):
    profile = tmp_path / 'profile'
    profile.mkdir()
    (profile / 'cookies.sqlite').write_bytes(b'')  # existence only; reader is patched
    monkeypatch.setenv('FIREFOX_PROFILE_DIR', str(profile))
    import familylink_server.cookie_refresher_app as app_mod

    monkeypatch.setattr(app_mod.browser_cookie3, 'firefox', lambda **kw: jar)
    if verify_ok:
        monkeypatch.setattr(app_mod, '_verify_family_link_access', lambda b64: None)
    else:

        def _boom(b64):
            raise RuntimeError(
                'Refreshed cookies failed Family Link API verification: HTTP 401'
            )

        monkeypatch.setattr(app_mod, '_verify_family_link_access', _boom)
    return TestClient(app_mod.app)


def test_refresh_returns_cookies_b64(monkeypatch, tmp_path):
    jar = [_FakeCookie('SAPISID'), _FakeCookie('SID', secure=False)]
    client = _client(monkeypatch, tmp_path, jar)
    resp = client.post('/refresh')
    assert resp.status_code == 200
    b64 = resp.json()['cookies_b64']
    text = base64.b64decode(b64).decode()
    assert 'SAPISID' in text
    assert text.startswith('# Netscape HTTP Cookie File')
