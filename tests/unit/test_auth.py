"""Tests for familylink.auth.CookieResolver."""

import base64

import pytest

from familylink.auth import CookieResolver

MINIMAL_COOKIES = (
    "# Netscape HTTP Cookie File\n"
    ".google.com\tTRUE\t/\tTRUE\t9999999999\tSAPISID\tmy_sapisid_value\n"
    ".google.com\tTRUE\t/\tTRUE\t9999999999\tSID\tsid_value\n"
)


def test_resolve_from_b64_env(monkeypatch):
    """CookieResolver resolves SAPISID from FAMILYLINK_COOKIES_B64 env var."""
    encoded = base64.b64encode(MINIMAL_COOKIES.encode()).decode()
    monkeypatch.setenv("FAMILYLINK_COOKIES_B64", encoded)
    monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
    monkeypatch.delenv("FAMILYLINK_COOKIE_FILE", raising=False)
    sapisid, jar = CookieResolver().resolve()
    assert sapisid == "my_sapisid_value"
    assert jar is not None


def test_resolve_from_sapisid_env(monkeypatch):
    """CookieResolver resolves SAPISID from FAMILYLINK_SAPISID env var (no jar)."""
    monkeypatch.delenv("FAMILYLINK_COOKIES_B64", raising=False)
    monkeypatch.setenv("FAMILYLINK_SAPISID", "env_sapisid")
    monkeypatch.delenv("FAMILYLINK_COOKIE_FILE", raising=False)
    sapisid, jar = CookieResolver().resolve()
    assert sapisid == "env_sapisid"
    assert jar is None


def test_resolve_from_cookie_file(monkeypatch, tmp_path):
    """CookieResolver resolves SAPISID from a cookie file when browser='txt'."""
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(MINIMAL_COOKIES)
    monkeypatch.delenv("FAMILYLINK_COOKIES_B64", raising=False)
    monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
    monkeypatch.delenv("FAMILYLINK_COOKIE_FILE", raising=False)
    monkeypatch.delenv("FAMILYLINK_PROFILES_DIR", raising=False)
    sapisid, jar = CookieResolver(browser="txt", cookie_file_path=cookie_file).resolve()
    assert sapisid == "my_sapisid_value"
    assert jar is not None


def test_resolve_raises_when_txt_browser_file_missing(monkeypatch, tmp_path):
    """CookieResolver raises ValueError when browser='txt' and cookie file is missing."""
    monkeypatch.delenv("FAMILYLINK_COOKIES_B64", raising=False)
    monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
    monkeypatch.delenv("FAMILYLINK_COOKIE_FILE", raising=False)
    monkeypatch.delenv("FAMILYLINK_PROFILES_DIR", raising=False)
    with pytest.raises(ValueError, match="Cookie file not found"):
        CookieResolver(
            browser="txt", cookie_file_path=tmp_path / "missing.txt"
        ).resolve()


def test_resolve_raises_when_no_source_available(monkeypatch):
    """CookieResolver raises RuntimeError when no source is available and browser_cookie3 is None."""
    monkeypatch.delenv("FAMILYLINK_COOKIES_B64", raising=False)
    monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
    monkeypatch.delenv("FAMILYLINK_COOKIE_FILE", raising=False)
    monkeypatch.delenv("FAMILYLINK_PROFILES_DIR", raising=False)
    # Patch browser_cookie3 to None so the last resort is unavailable
    import familylink.auth as auth_mod

    monkeypatch.setattr(auth_mod, "browser_cookie3", None)
    with pytest.raises(RuntimeError):
        CookieResolver(browser="txt").resolve()
