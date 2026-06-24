"""Tests for the FastAPI application factory."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient


@pytest.fixture
def mock_init_service():
    """Mock init_service to avoid actual FamilyLink instantiation."""
    with patch("familylink_server.main.init_service"):
        yield


def test_docs_endpoint_exists(mock_init_service):
    """FastAPI Swagger UI docs should be available at /docs."""
    from familylink_server.main import app

    client = TestClient(app)
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_openapi_json_exists(mock_init_service):
    """OpenAPI schema should be available at /openapi.json."""
    from familylink_server.main import app

    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert "familylink" in resp.json()["info"]["title"].lower()


def test_auth_login_route_exists(mock_init_service):
    """GET /auth/login should redirect to Google OAuth."""
    from familylink_server.main import app

    mock_redirect = RedirectResponse(
        url="https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=test",
        status_code=302,
    )
    with patch(
        "familylink_server.auth.oauth._oauth.google.authorize_redirect",
        new=AsyncMock(return_value=mock_redirect),
    ):
        client = TestClient(app)
        resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code in (302, 307)


async def test_bot_not_started_when_discord_disabled():
    """Lifespan should not create a bot task when Discord vars are absent."""
    from familylink_server.main import app, lifespan

    with (
        patch("familylink_server.main.init_service"),
        patch("familylink_server.main.settings") as mock_settings,
        patch("familylink_server.main.asyncio.create_task") as mock_create_task,
    ):
        mock_settings.discord_enabled = False
        async with lifespan(app):
            pass
        mock_create_task.assert_not_called()
