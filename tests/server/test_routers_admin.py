"""Tests for the /admin router's refresher-bootstrap proxy endpoint."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from familylink_server.config import settings
from familylink_server.main import app as main_app
from familylink_server.routers.admin import router as admin_router
from familylink_server.services.family_link import get_service


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


def test_sapisid_relay_reconnects_with_valid_token(monkeypatch):
    """POST /admin/sapisid-relay with the correct token hot-swaps the client."""
    monkeypatch.setattr(settings, 'sapisid_relay_token', 'phone-secret')

    mock_svc = MagicMock()
    mock_svc.reinit_with_sapisid = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))
    mock_svc.set_auth_failed = MagicMock()

    main_app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        main_client = TestClient(main_app)
        resp = main_client.post(
            '/admin/sapisid-relay',
            data={'sapisid': 'abc123', 'token': 'phone-secret'},
        )
    finally:
        main_app.dependency_overrides.pop(get_service, None)

    assert resp.status_code == 200
    assert 'Reconnected' in resp.text
    mock_svc.reinit_with_sapisid.assert_called_once_with('abc123')
    mock_svc.get_members.assert_called_once()
    mock_svc.set_auth_failed.assert_called_once_with(False)


def test_sapisid_relay_forbidden_when_wrong_token(monkeypatch):
    """POST /admin/sapisid-relay returns 403 when the token doesn't match."""
    monkeypatch.setattr(settings, 'sapisid_relay_token', 'phone-secret')

    mock_svc = MagicMock()
    mock_svc.reinit_with_sapisid = MagicMock()

    main_app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        main_client = TestClient(main_app)
        resp = main_client.post(
            '/admin/sapisid-relay',
            data={'sapisid': 'abc123', 'token': 'wrong'},
        )
    finally:
        main_app.dependency_overrides.pop(get_service, None)

    assert resp.status_code == 403
    mock_svc.reinit_with_sapisid.assert_not_called()


def test_sapisid_relay_forbidden_when_token_unset(monkeypatch):
    """POST /admin/sapisid-relay returns 403 when SAPISID_RELAY_TOKEN is unset."""
    monkeypatch.setattr(settings, 'sapisid_relay_token', '')

    mock_svc = MagicMock()
    main_app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        main_client = TestClient(main_app)
        resp = main_client.post(
            '/admin/sapisid-relay',
            data={'sapisid': 'abc123', 'token': ''},
        )
    finally:
        main_app.dependency_overrides.pop(get_service, None)

    assert resp.status_code == 403


def test_sapisid_relay_forbidden_when_token_field_omitted(monkeypatch):
    """POST /admin/sapisid-relay returns 403 when the token field is absent entirely."""
    monkeypatch.setattr(settings, 'sapisid_relay_token', 'phone-secret')

    mock_svc = MagicMock()
    main_app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        main_client = TestClient(main_app)
        resp = main_client.post(
            '/admin/sapisid-relay',
            data={'sapisid': 'abc123'},
        )
    finally:
        main_app.dependency_overrides.pop(get_service, None)

    assert resp.status_code == 403
    mock_svc.reinit_with_sapisid.assert_not_called()


def test_sapisid_relay_reports_failure_when_verification_fails(monkeypatch):
    """POST /admin/sapisid-relay returns 502 when get_members() raises after swap."""
    monkeypatch.setattr(settings, 'sapisid_relay_token', 'phone-secret')

    mock_svc = MagicMock()
    mock_svc.reinit_with_sapisid = MagicMock()
    mock_svc.get_members = AsyncMock(side_effect=RuntimeError('auth failed'))
    mock_svc.set_auth_failed = MagicMock()

    main_app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        main_client = TestClient(main_app)
        resp = main_client.post(
            '/admin/sapisid-relay',
            data={'sapisid': 'abc123', 'token': 'phone-secret'},
        )
    finally:
        main_app.dependency_overrides.pop(get_service, None)

    assert resp.status_code == 502
    mock_svc.reinit_with_sapisid.assert_called_once_with('abc123')
