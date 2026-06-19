"""Tests for the /api/members router."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer

from familylink_server.config import settings
from familylink_server.services.family_link import get_service


def _session_cookie():
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": settings.familylink_google_email})


@pytest.fixture
def client():
    """Provide a TestClient with FamilyLinkService mocked out."""
    # Patch FamilyLinkService init so no real Google auth needed
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(
            members=[
                MagicMock(
                    user_id="child1",
                    profile=MagicMock(display_name="Alice", email="alice@example.com"),
                    member_supervision_info=MagicMock(is_supervised_member=True),
                )
            ]
        )
    )

    with (
        patch("familylink_server.main.init_service", return_value=mock_svc),
        patch("familylink_server.services.family_link._service", mock_svc),
    ):
        from familylink_server.main import app

        # Override the get_service dependency so it returns our mock directly,
        # bypassing the _service singleton check
        app.dependency_overrides[get_service] = lambda: mock_svc
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.pop(get_service, None)


def test_get_members_returns_200(client):
    """GET /api/members with a valid session cookie returns 200 and a list."""
    resp = client.get("/api/members", cookies={"fl_session": _session_cookie()})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_get_members_rejects_no_session(client):
    """GET /api/members without a session cookie returns 401."""
    resp = client.get("/api/members")
    assert resp.status_code == 401
