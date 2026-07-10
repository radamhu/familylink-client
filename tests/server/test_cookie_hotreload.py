"""Tests for cookie hot-reload endpoint and FamilyLinkService methods."""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

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


def test_reinit_with_cookies_creates_new_client():
    """reinit_with_cookies should replace _client with a new FamilyLink instance."""
    svc = _make_service()
    old_client = svc._client

    with patch('familylink_server.services.family_link.FamilyLink') as MockFamilyLink:
        MockFamilyLink.return_value = MagicMock()
        svc.reinit_with_cookies('test_sapisid_value')

    # New client was created
    assert svc._client is not old_client
    # FAMILYLINK_SAPISID was set before creating the new client
    MockFamilyLink.assert_called_once()


def test_reinit_with_cookies_clears_caches():
    """reinit_with_cookies should clear member/usage caches and reset auth_failed."""
    svc = _make_service()
    svc._members_cache = (MagicMock(), MagicMock())
    svc._usage_cache = {'child1': (MagicMock(), MagicMock())}
    svc._auth_failed = True

    with patch('familylink_server.services.family_link.FamilyLink'):
        svc.reinit_with_cookies('new_sapisid')

    assert svc._members_cache is None
    assert svc._usage_cache == {}
    assert svc._auth_failed is False


def test_reinit_with_cookies_sets_env_var():
    """reinit_with_cookies should set FAMILYLINK_SAPISID in the environment."""
    svc = _make_service()

    with patch('familylink_server.services.family_link.FamilyLink'):
        with patch.dict(os.environ, {}, clear=False):
            svc.reinit_with_cookies('MY_SAPISID_VALUE')
            assert os.environ.get('FAMILYLINK_SAPISID') == 'MY_SAPISID_VALUE'


@pytest.fixture
def test_client():
    """Return a TestClient with init_service patched out."""
    with patch('familylink_server.main.init_service'):
        from familylink_server.main import app

        return TestClient(app, raise_server_exceptions=False)


def test_refresh_cookies_requires_auth(test_client):
    """POST /admin/refresh-cookies without a session cookie should return 401."""
    resp = test_client.post('/admin/refresh-cookies', json={'sapisid': 'test'})
    assert resp.status_code == 401


def test_refresh_cookies_accepts_sapisid(test_client):
    """POST /admin/refresh-cookies with valid session and SAPISID should return 204."""
    mock_svc = _make_service()

    with (
        patch('familylink_server.main.init_service'),
        patch('familylink_server.routers.admin.get_service', return_value=mock_svc),
        patch('familylink_server.services.family_link.FamilyLink'),
    ):
        from itsdangerous import URLSafeSerializer

        from familylink_server.config import settings

        signer = URLSafeSerializer(settings.secret_key, salt='fl-session')
        session_cookie = signer.dumps({'email': settings.familylink_google_email})

        resp = test_client.post(
            '/admin/refresh-cookies',
            json={'sapisid': 'fresh_sapisid_value'},
            cookies={'fl_session': session_cookie},
        )

    assert resp.status_code == 204
