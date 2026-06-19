"""Tests for Google OAuth login flow and require_user session dependency."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer
from starlette.middleware.sessions import SessionMiddleware

from familylink_server.auth.oauth import require_user
from familylink_server.auth.oauth import router as auth_router
from familylink_server.config import settings


@pytest.fixture
def app():
    """Create a FastAPI test app with the auth router and a protected route."""
    application = FastAPI()
    application.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
    application.include_router(auth_router)

    @application.get("/protected")
    async def protected(email: str = require_user):  # type: ignore[assignment]
        return {"email": email}

    return application


@pytest.fixture
def client(app):
    """Return a TestClient for the test app."""
    return TestClient(app, raise_server_exceptions=True)


def _make_session_cookie(email: str) -> str:
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": email})


def test_protected_route_rejects_no_cookie(client):
    """A request without a session cookie must be rejected with 401."""
    resp = client.get("/protected")
    assert resp.status_code == 401


def test_protected_route_accepts_valid_cookie(client):
    """A request with a valid signed cookie for the owner email must succeed."""
    cookie = _make_session_cookie(settings.familylink_google_email)
    resp = client.get("/protected", cookies={"fl_session": cookie})
    assert resp.status_code == 200
    assert resp.json()["email"] == settings.familylink_google_email


def test_protected_route_rejects_wrong_email(client):
    """A valid cookie for a different email must be rejected with 403."""
    cookie = _make_session_cookie("intruder@gmail.com")
    resp = client.get("/protected", cookies={"fl_session": cookie})
    assert resp.status_code == 403


def test_auth_login_redirects_to_google(client):
    """GET /auth/login must redirect to accounts.google.com."""
    mock_redirect = RedirectResponse(
        url="https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=test",
        status_code=302,
    )
    with patch(
        "familylink_server.auth.oauth._oauth.google.authorize_redirect",
        new=AsyncMock(return_value=mock_redirect),
    ):
        resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "accounts.google.com" in resp.headers.get("location", "")


def test_auth_logout_clears_cookie(client):
    """GET /auth/logout must redirect and clear the fl_session cookie."""
    cookie = _make_session_cookie(settings.familylink_google_email)
    resp = client.get(
        "/auth/logout", cookies={"fl_session": cookie}, follow_redirects=False
    )
    assert resp.status_code in (302, 307)
    assert resp.cookies.get("fl_session") == "" or "fl_session" not in resp.cookies
