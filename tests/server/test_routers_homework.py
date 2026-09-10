"""Tests for the internal /internal/ekreta credentials/homework endpoints."""

from datetime import date
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
            json={'child_id': 'child1', 'entries': []},
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 401


@freeze_time('2026-09-08')
def test_ingest_upserts_and_prunes(monkeypatch):
    """Time is frozen so the asserted 'today' never drifts."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    import familylink_server.routers.homework as homework_router

    upsert_mock = AsyncMock(return_value=[])
    prune_mock = AsyncMock()
    monkeypatch.setattr(homework_router, 'upsert_homework_entries', upsert_mock)
    monkeypatch.setattr(homework_router, 'prune_expired_homework', prune_mock)
    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={
                'child_id': 'child1',
                'entries': [
                    {
                        'subject': 'Matek',
                        'teacher': 'Kovács Tanárnő',
                        'deadline': '2026-09-10',
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
    upsert_mock.assert_awaited_once()
    call_args = upsert_mock.await_args.args
    assert call_args[1] == 'child1'
    assert call_args[2] == date(2026, 9, 8)
    assert call_args[3] == [
        {
            'subject': 'Matek',
            'deadline': date(2026, 9, 10),
            'description': 'Teacher: Kovács Tanárnő\nOldd meg a 12. feladatot.',
        }
    ]
    prune_mock.assert_awaited_once()
    prune_call_args = prune_mock.await_args.args
    assert prune_call_args[1] == 'child1'
    assert prune_call_args[2] == date(2026, 9, 8)


@freeze_time('2026-09-08')
def test_ingest_notifies_ntfy_for_new_homework_only(monkeypatch):
    """Only entries upsert_homework_entries reports as new trigger a push."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    import familylink_server.routers.homework as homework_router

    monkeypatch.setattr(
        homework_router,
        'upsert_homework_entries',
        AsyncMock(
            return_value=[
                {
                    'subject': 'Matek',
                    'deadline': date(2026, 9, 10),
                    'description': 'x',
                }
            ]
        ),
    )
    monkeypatch.setattr(homework_router, 'prune_expired_homework', AsyncMock())
    mock_ntfy = AsyncMock()
    monkeypatch.setattr(homework_router, 'get_notifier', lambda: mock_ntfy)

    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={
                'child_id': 'child1',
                'entries': [
                    {
                        'subject': 'Matek',
                        'teacher': '',
                        'deadline': '2026-09-10',
                        'text': '',
                        'attachments': [],
                    }
                ],
            },
            headers={'X-Api-Key': 'secret'},
        )
    finally:
        _pop_session_override()

    assert resp.status_code == 204
    mock_ntfy.notify_homework.assert_awaited_once_with('child1', 'Matek', '2026-09-10')


@freeze_time('2026-09-08')
def test_ingest_skips_ntfy_when_no_new_entries(monkeypatch):
    """upsert_homework_entries reports no new entries -> notify_homework is never called."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    import familylink_server.routers.homework as homework_router

    monkeypatch.setattr(
        homework_router, 'upsert_homework_entries', AsyncMock(return_value=[])
    )
    monkeypatch.setattr(homework_router, 'prune_expired_homework', AsyncMock())
    mock_ntfy = AsyncMock()
    monkeypatch.setattr(homework_router, 'get_notifier', lambda: mock_ntfy)

    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={'child_id': 'child1', 'entries': []},
            headers={'X-Api-Key': 'secret'},
        )
    finally:
        _pop_session_override()

    assert resp.status_code == 204
    mock_ntfy.notify_homework.assert_not_awaited()


@freeze_time('2026-09-08')
def test_ingest_skips_ntfy_when_disabled(monkeypatch):
    """get_notifier() returns None (ntfy not configured) -> no error."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    import familylink_server.routers.homework as homework_router

    monkeypatch.setattr(
        homework_router,
        'upsert_homework_entries',
        AsyncMock(
            return_value=[
                {'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'x'}
            ]
        ),
    )
    monkeypatch.setattr(homework_router, 'prune_expired_homework', AsyncMock())
    monkeypatch.setattr(homework_router, 'get_notifier', lambda: None)

    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={'child_id': 'child1', 'entries': []},
            headers={'X-Api-Key': 'secret'},
        )
    finally:
        _pop_session_override()

    assert resp.status_code == 204
