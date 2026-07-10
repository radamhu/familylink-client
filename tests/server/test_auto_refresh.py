"""Tests for auto-refresh via sidecar."""

import asyncio  # noqa: F401
import os
from unittest.mock import MagicMock, patch

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

    assert settings.cookie_refresher_url == ""


def test_reinit_with_cookies_b64_sets_env():
    """reinit_with_cookies_b64 should set FAMILYLINK_COOKIES_B64 in os.environ."""
    svc = _make_service()
    with patch("familylink_server.services.family_link.FamilyLink"):
        with patch.dict(os.environ, {}, clear=False):
            svc.reinit_with_cookies_b64("new_b64_value")
            assert os.environ.get("FAMILYLINK_COOKIES_B64") == "new_b64_value"


def test_reinit_with_cookies_b64_pops_sapisid():
    """reinit_with_cookies_b64 should remove FAMILYLINK_SAPISID from os.environ."""
    svc = _make_service()
    with patch("familylink_server.services.family_link.FamilyLink"):
        with patch.dict(os.environ, {"FAMILYLINK_SAPISID": "old_sid"}, clear=False):
            svc.reinit_with_cookies_b64("new_b64_value")
            assert "FAMILYLINK_SAPISID" not in os.environ


def test_reinit_with_cookies_b64_clears_caches():
    """reinit_with_cookies_b64 should clear caches and reset auth_failed."""
    svc = _make_service()
    svc._members_cache = (MagicMock(), MagicMock())
    svc._usage_cache = {"child1": (MagicMock(), MagicMock())}
    svc._auth_failed = True

    with patch("familylink_server.services.family_link.FamilyLink"):
        svc.reinit_with_cookies_b64("abc")

    assert svc._members_cache is None
    assert svc._usage_cache == {}
    assert svc._auth_failed is False


def test_reinit_with_cookies_b64_creates_new_client():
    """reinit_with_cookies_b64 should replace _client with new FamilyLink instance."""
    svc = _make_service()
    old_client = svc._client

    with patch("familylink_server.services.family_link.FamilyLink") as MockFL:
        MockFL.return_value = MagicMock()
        svc.reinit_with_cookies_b64("abc")

    assert svc._client is not old_client
    MockFL.assert_called_once()
