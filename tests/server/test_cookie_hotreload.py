"""Tests for FamilyLinkService's auth_failed flag."""

from unittest.mock import MagicMock

from familylink_server.services.family_link import FamilyLinkService


def _make_service():
    """Create a service instance bypassing __init__ (avoids FamilyLink() cookie lookup)."""
    svc = FamilyLinkService.__new__(FamilyLinkService)
    svc._ttl = 0
    svc._members_cache = None
    svc._usage_cache = {}
    svc._auth_failed = False
    svc._client = MagicMock()
    return svc


def test_auth_failed_starts_false():
    """auth_failed property should return False on a fresh instance."""
    svc = _make_service()
    assert svc.auth_failed is False


def test_set_auth_failed_true():
    """set_auth_failed(True) should make auth_failed return True."""
    svc = _make_service()
    svc.set_auth_failed(True)
    assert svc.auth_failed is True


def test_set_auth_failed_false():
    """set_auth_failed(False) after True should make auth_failed return False."""
    svc = _make_service()
    svc.set_auth_failed(True)
    svc.set_auth_failed(False)
    assert svc.auth_failed is False
