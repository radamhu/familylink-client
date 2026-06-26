"""Tests for the dashboard (/) and history (/history) routers."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer

from familylink_server.config import settings
from familylink_server.db import get_session


def _cookie():
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": settings.familylink_google_email})


def _fake_session(machines=None):
    """Return an async generator yielding a mock session."""
    machines = machines or []

    async def _gen():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = machines
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session

    return _gen


def test_dashboard_returns_200():
    """GET / with a valid session and no children returns 200 with 'Family Link'."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))
    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get("/", cookies={"fl_session": _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert "Family Link" in resp.text


def test_dashboard_shows_linux_machine_for_child():
    """Dashboard renders Linux machine name when child has a registered machine."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.child_id = "child1"
    mock_machine.friendly_name = "Gaming PC"
    mock_machine.daily_limit_mins = 60
    mock_machine.enabled = True

    child = MagicMock()
    child.user_id = "child1"
    child.profile.display_name = "Alice"
    child.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session(machines=[mock_machine])
    try:
        client = TestClient(app)
        resp = client.get("/", cookies={"fl_session": _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert "Gaming PC" in resp.text


def test_history_returns_200():
    """GET /history with a valid session returns 200."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get("/history", cookies={"fl_session": _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
