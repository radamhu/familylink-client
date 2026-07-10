"""Tests for auto-refresh via sidecar."""

import asyncio  # noqa: F401
from unittest.mock import MagicMock

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
