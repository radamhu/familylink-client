"""Tests for the cookie-refresher bootstrap script's pure conversion logic."""


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
