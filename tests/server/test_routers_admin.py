"""Tests for the /admin router's refresher-bootstrap proxy endpoint."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from familylink_server.config import settings
from familylink_server.routers.admin import router as admin_router


@pytest.fixture
def client():
    """Provide a TestClient with only the admin router mounted (no lifespan)."""
    app = FastAPI()
    app.include_router(admin_router)
    return TestClient(app)


def test_refresher_bootstrap_proxies_to_sidecar(client, httpx_mock, monkeypatch):
    """POST /admin/refresher-bootstrap forwards the body to the sidecar's /bootstrap."""
    monkeypatch.setattr(
        settings, 'cookie_refresher_url', 'http://cookie-refresher:8080'
    )
    monkeypatch.setattr(settings, 'refresher_api_key', 'secret')

    httpx_mock.add_response(
        url='http://cookie-refresher:8080/bootstrap',
        method='POST',
        status_code=204,
    )

    resp = client.post(
        '/admin/refresher-bootstrap',
        json={'cookies': [{'name': 'SAPISID', 'value': 'abc'}], 'origins': []},
        headers={'X-Api-Key': 'secret'},
    )
    assert resp.status_code == 204

    request = httpx_mock.get_requests()[-1]
    assert request.headers['X-Api-Key'] == 'secret'
    assert b'SAPISID' in request.content


def test_refresher_bootstrap_forbidden_when_wrong_key(client, monkeypatch):
    """POST /admin/refresher-bootstrap returns 403 when X-Api-Key doesn't match."""
    monkeypatch.setattr(
        settings, 'cookie_refresher_url', 'http://cookie-refresher:8080'
    )
    monkeypatch.setattr(settings, 'refresher_api_key', 'secret')

    resp = client.post(
        '/admin/refresher-bootstrap',
        json={'cookies': [], 'origins': []},
        headers={'X-Api-Key': 'wrong'},
    )
    assert resp.status_code == 403


def test_refresher_bootstrap_fails_when_sidecar_not_configured(client, monkeypatch):
    """POST /admin/refresher-bootstrap returns 400 when COOKIE_REFRESHER_URL is unset."""
    monkeypatch.setattr(settings, 'cookie_refresher_url', '')
    monkeypatch.setattr(settings, 'refresher_api_key', 'secret')

    resp = client.post(
        '/admin/refresher-bootstrap',
        json={'cookies': [], 'origins': []},
        headers={'X-Api-Key': 'secret'},
    )
    assert resp.status_code == 400


def test_refresher_bootstrap_surfaces_sidecar_error(client, httpx_mock, monkeypatch):
    """POST /admin/refresher-bootstrap returns 502 with detail when the sidecar rejects it."""
    monkeypatch.setattr(
        settings, 'cookie_refresher_url', 'http://cookie-refresher:8080'
    )
    monkeypatch.setattr(settings, 'refresher_api_key', 'secret')

    httpx_mock.add_response(
        url='http://cookie-refresher:8080/bootstrap',
        method='POST',
        status_code=401,
        text='bad sidecar key',
    )

    resp = client.post(
        '/admin/refresher-bootstrap',
        json={'cookies': [], 'origins': []},
        headers={'X-Api-Key': 'secret'},
    )
    assert resp.status_code == 502
    assert '401' in resp.text
    assert 'bad sidecar key' in resp.text
