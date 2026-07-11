"""Tests for the cookie-refresher bootstrap script's pure conversion logic."""

import sys


class _FakeCookie:
    def __init__(self, domain, name, value, path='/', expires=123, secure=True):
        self.domain = domain
        self.name = name
        self.value = value
        self.path = path
        self.expires = expires
        self.secure = secure


def test_cookiejar_to_storage_state_filters_and_converts():
    """Only google.com cookies are kept; fields map to Playwright's schema."""
    from scripts.bootstrap_refresher_session import _cookiejar_to_storage_state

    cookies = [
        _FakeCookie('.google.com', 'SAPISID', 'abc'),
        _FakeCookie('.example.com', 'OTHER', 'xyz'),
    ]
    result = _cookiejar_to_storage_state(cookies)

    assert result['origins'] == []
    assert len(result['cookies']) == 1
    c = result['cookies'][0]
    assert c['name'] == 'SAPISID'
    assert c['domain'] == '.google.com'
    assert c['secure'] is True
    assert c['sameSite'] == 'None'


def test_cookiejar_to_storage_state_handles_missing_expires():
    """A session cookie (expires=None/0) maps to Playwright's -1 sentinel."""
    from scripts.bootstrap_refresher_session import _cookiejar_to_storage_state

    cookies = [_FakeCookie('.google.com', 'SID', 'v', expires=0)]
    result = _cookiejar_to_storage_state(cookies)

    assert result['cookies'][0]['expires'] == -1


def test_main_requires_env_vars(monkeypatch, capsys):
    """main() bails out before touching browser_cookie3 when env vars are unset."""
    from scripts.bootstrap_refresher_session import main

    monkeypatch.delenv('WEB_BASE_URL', raising=False)
    monkeypatch.delenv('REFRESHER_API_KEY', raising=False)
    monkeypatch.setattr('sys.argv', ['bootstrap_refresher_session.py'])

    result = main()

    assert result == 1
    assert 'Set WEB_BASE_URL and REFRESHER_API_KEY' in capsys.readouterr().err


def test_main_requires_sapisid_cookie(monkeypatch, capsys):
    """main() bails out before calling httpx.post when no SAPISID cookie is found."""
    from scripts.bootstrap_refresher_session import main

    monkeypatch.setenv('WEB_BASE_URL', 'https://example.com')
    monkeypatch.setenv('REFRESHER_API_KEY', 'secret')
    monkeypatch.setattr('sys.argv', ['bootstrap_refresher_session.py'])

    class _FakeBrowserCookie3:
        @staticmethod
        def chrome(domain_name=None):
            return [_FakeCookie('.google.com', 'OTHER', 'xyz')]

    monkeypatch.setitem(sys.modules, 'browser_cookie3', _FakeBrowserCookie3())

    result = main()

    assert result == 1
    assert 'No SAPISID cookie found' in capsys.readouterr().err
