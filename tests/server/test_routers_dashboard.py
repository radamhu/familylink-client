"""Tests for the dashboard (/) and history (/history) routers."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer

from familylink_server.config import settings


def _cookie():
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": settings.familylink_google_email})


def test_dashboard_returns_200():
    """GET / with a valid session and no children returns 200 with 'Family Link'."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))
    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.get("/", cookies={"fl_session": _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    assert "Family Link" in resp.text


def test_history_returns_200():
    """GET /history with a valid session returns 200."""
    from familylink_server.db import get_session
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))

    async def fake_session():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = fake_session
    try:
        client = TestClient(app)
        resp = client.get("/history", cookies={"fl_session": _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
