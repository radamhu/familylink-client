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


def test_refresh_forbidden_when_wrong_key(monkeypatch, tmp_path):
    monkeypatch.setenv('REFRESHER_API_KEY', 'secret')
    jar = [_FakeCookie('SAPISID')]
    client = _client(monkeypatch, tmp_path, jar)
    resp = client.post('/refresh', headers={'X-Api-Key': 'wrong'})
    assert resp.status_code == 403


def test_refresh_409_when_no_profile(monkeypatch, tmp_path):
    monkeypatch.setenv('FIREFOX_PROFILE_DIR', str(tmp_path / 'missing'))
    import familylink_server.cookie_refresher_app as app_mod

    resp = TestClient(app_mod.app).post('/refresh')
    assert resp.status_code == 409


def test_refresh_409_when_no_sapisid(monkeypatch, tmp_path):
    jar = [_FakeCookie('NID')]  # no SAPISID
    client = _client(monkeypatch, tmp_path, jar)
    resp = client.post('/refresh')
    assert resp.status_code == 409


def test_refresh_502_when_session_dead(monkeypatch, tmp_path):
    jar = [_FakeCookie('SAPISID')]
    client = _client(monkeypatch, tmp_path, jar, verify_ok=False)
    resp = client.post('/refresh')
    assert resp.status_code == 502
    assert 'verification' in resp.json()['detail']
