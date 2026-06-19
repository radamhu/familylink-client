"""Tests for the /devices router and HTMX lock/unlock endpoints."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer

from familylink_server.config import settings


def _cookie():
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": settings.familylink_google_email})


def test_devices_page_returns_200():
    """GET /devices with a valid session returns 200 and device names."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

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
            device_info=[
                MagicMock(
                    device_id="dev1", display_info=MagicMock(friendly_name="Pixel 7")
                )
            ],
        )
    )
    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.get("/devices", cookies={"fl_session": _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    assert "Pixel 7" in resp.text


def test_lock_device_returns_partial_html():
    """POST /devices/{id}/lock returns an HTML partial containing 'locked'."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.lock_device = AsyncMock(return_value=None)
    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.post(
            "/devices/dev1/lock",
            data={"child_id": "child1"},
            cookies={"fl_session": _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    assert "locked" in resp.text.lower()
