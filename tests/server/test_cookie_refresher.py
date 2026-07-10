"""Tests for the cookie-refresher sidecar app."""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def test_to_netscape_subdomain_flag():
    """Domains starting with '.' should use TRUE for include_subdomains."""
    from familylink_server.cookie_refresher_app import _to_netscape
    cookies = [{'name': 'SAPISID', 'value': 'abc/def', 'domain': '.google.com',
                'path': '/', 'expires': 1234567890.0, 'secure': True}]
    result = _to_netscape(cookies)
    assert result.startswith('# Netscape HTTP Cookie File\n')
    assert '.google.com\tTRUE\t/\tTRUE\t1234567890\tSAPISID\tabc/def' in result


def test_to_netscape_non_subdomain():
    """Domains not starting with '.' should use FALSE for include_subdomains."""
    from familylink_server.cookie_refresher_app import _to_netscape
    cookies = [{'name': 'SESSION', 'value': 'xyz', 'domain': 'accounts.google.com',
                'path': '/', 'expires': 0, 'secure': False}]
    result = _to_netscape(cookies)
    assert 'accounts.google.com\tFALSE\t/\tFALSE\t0\tSESSION\txyz' in result


def test_to_netscape_missing_expires():
    """Cookies without 'expires' key should default to expiry 0."""
    from familylink_server.cookie_refresher_app import _to_netscape
    cookies = [{'name': 'X', 'value': 'y', 'domain': '.g.com', 'path': '/', 'secure': False}]
    result = _to_netscape(cookies)
    assert '\t0\tX\ty' in result


def test_health_endpoint():
    """GET /health should return 200 with status ok."""
    from familylink_server.cookie_refresher_app import app
    client = TestClient(app)
    resp = client.get('/health')
    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok'}
