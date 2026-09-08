"""Tests for the internal /internal/ekreta credentials/homework endpoints."""

from datetime import date, timedelta
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from freezegun import freeze_time

from familylink_server.config import settings
from familylink_server.db import get_session
from familylink_server.db.models import EkretaCredential


def _client():
    from familylink_server.main import app

    app.dependency_overrides[get_session] = lambda: AsyncMock()
    return TestClient(app)


def _pop_session_override():
    from familylink_server.main import app

    app.dependency_overrides.pop(get_session, None)


def test_credentials_requires_token(monkeypatch):
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    client = _client()
    try:
        resp = client.get('/internal/ekreta/credentials')
    finally:
        _pop_session_override()
    assert resp.status_code == 401


def test_credentials_rejects_when_no_token_configured(monkeypatch):
    """No configured token must mean 'closed', not 'open'."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', '')
    client = _client()
    try:
        resp = client.get(
            '/internal/ekreta/credentials', headers={'X-Api-Key': 'anything'}
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 401


def test_credentials_rejects_same_length_wrong_token(monkeypatch):
    """A wrong token of the same length must still be rejected (constant-time compare)."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    client = _client()
    try:
        resp = client.get(
            '/internal/ekreta/credentials', headers={'X-Api-Key': 'wr0ng!'}
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 401


def test_credentials_returns_rows(monkeypatch):
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    import familylink_server.routers.homework as homework_router

    monkeypatch.setattr(
        homework_router,
        'list_ekreta_credentials',
        AsyncMock(
            return_value=[
                EkretaCredential(
                    child_id='child1',
                    username='anna.kovacs',
                    password='pw',
                    institution_code='035120',
                )
            ]
        ),
    )
    client = _client()
    try:
        resp = client.get(
            '/internal/ekreta/credentials', headers={'X-Api-Key': 'secret'}
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 200
    assert resp.json() == [
        {
            'child_id': 'child1',
            'username': 'anna.kovacs',
            'password': 'pw',
            'institution_code': '035120',
        }
    ]


def test_ingest_requires_token():
    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={'child_id': 'child1', 'date': '2026-09-08', 'entries': []},
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 401


@freeze_time('2026-09-08')
def test_ingest_replaces_and_prunes(monkeypatch):
    """Time is frozen so the asserted retention cutoff never drifts from 'today'."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    monkeypatch.setattr(settings, 'ekreta_retention_days', 30)
    import familylink_server.routers.homework as homework_router

    replace_mock = AsyncMock()
    prune_mock = AsyncMock()
    monkeypatch.setattr(homework_router, 'replace_homework_for_day', replace_mock)
    monkeypatch.setattr(homework_router, 'prune_homework_before', prune_mock)
    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={
                'child_id': 'child1',
                'date': '2026-09-08',
                'entries': [
                    {
                        'subject': 'Matek',
                        'teacher': 'Kovács Tanárnő',
                        'deadline': '2026-09-09',
                        'text': 'Oldd meg a 12. feladatot.',
                        'attachments': [],
                    }
                ],
            },
            headers={'X-Api-Key': 'secret'},
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 204
    replace_mock.assert_awaited_once()
    call_args = replace_mock.await_args.args
    assert call_args[1] == 'child1'
    assert call_args[2].isoformat() == '2026-09-08'
    assert call_args[3] == [
        {
            'subject': 'Matek',
            'description': (
                'Teacher: Kovács Tanárnő\n'
                'Deadline: 2026-09-09\n'
                'Oldd meg a 12. feladatot.'
            ),
        }
    ]
    prune_mock.assert_awaited_once()
    prune_call_args = prune_mock.await_args.args
    assert prune_call_args[1] == 'child1'
    assert prune_call_args[2] == date.today() - timedelta(days=30)
