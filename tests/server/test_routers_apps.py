"""Tests for the /apps router and HTMX limit/block/allow endpoints."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer

from familylink_server.config import settings


def _cookie():
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": settings.familylink_google_email})


def _make_app_mock(title, package, hidden=False, limit_mins=None, always_allowed=False):
    app_mock = MagicMock()
    app_mock.title = title
    app_mock.package_name = package
    app_mock.supervision_setting.hidden = hidden
    app_mock.supervision_setting.usage_limit = (
        MagicMock(daily_usage_limit_mins=limit_mins, enabled=True)
        if limit_mins
        else None
    )
    app_mock.supervision_setting.always_allowed_app_info = (
        MagicMock(always_allowed_state="alwaysAllowedStateEnabled")
        if always_allowed
        else None
    )
    return app_mock


def _make_client(mock_svc):
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    client = TestClient(app)
    return client


def test_apps_page_returns_200():
    """GET /apps with a valid session returns 200 and app titles."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(
            members=[
                MagicMock(
                    user_id="child1",
                    member_supervision_info=MagicMock(is_supervised_member=True),
                )
            ]
        )
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=MagicMock(
            apps=[
                _make_app_mock("YouTube", "com.google.android.youtube", limit_mins=30)
            ],
            device_info=[],
            app_usage_sessions=[],
        )
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.get("/apps", cookies={"fl_session": _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    assert "YouTube" in resp.text


def test_set_limit_returns_partial(monkeypatch):
    """POST /apps/{package}/limit calls set_app_limit with int minutes and returns 200."""
    mock_svc = MagicMock()
    mock_svc.set_app_limit = AsyncMock(return_value=None)
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.post(
            "/apps/com.google.android.youtube/limit",
            data={"child_id": "child1", "minutes": "45"},
            cookies={"fl_session": _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    mock_svc.set_app_limit.assert_called_once_with(
        "com.google.android.youtube", 45, child_id="child1"
    )


def test_block_app_returns_partial():
    """POST /apps/{package}/block calls block_app and returns 200 with partial HTML."""
    mock_svc = MagicMock()
    mock_svc.block_app = AsyncMock(return_value=None)
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.post(
            "/apps/com.google.android.youtube/block",
            data={"child_id": "child1"},
            cookies={"fl_session": _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    mock_svc.block_app.assert_called_once_with(
        "com.google.android.youtube", child_id="child1"
    )
