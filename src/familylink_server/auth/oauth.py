"""Google OAuth 2.0 login flow and session cookie dependency."""

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

from familylink_server.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

_oauth = OAuth()
_oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

_signer = URLSafeSerializer(settings.secret_key, salt="fl-session")
_COOKIE_NAME = "fl_session"


def _make_session(email: str) -> str:
    return _signer.dumps({"email": email})


def _read_session(token: str) -> dict | None:
    try:
        return _signer.loads(token)
    except BadSignature:
        return None


async def _require_user(fl_session: str | None = Cookie(default=None)) -> str:
    """FastAPI dependency — returns authenticated user email or raises HTTP 401/403."""
    if not fl_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = _read_session(fl_session)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid session")
    email = payload.get("email", "")
    if email != settings.familylink_google_email:
        raise HTTPException(status_code=403, detail="Access denied")
    return email


# Expose as a Depends instance so it can be used directly as a default value:
#   async def route(email: str = require_user): ...
require_user = Depends(_require_user)


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    """Redirect the browser to Google's OAuth 2.0 authorization page."""
    redirect_uri = str(request.url_for("auth_callback"))
    return await _oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(request: Request) -> RedirectResponse:
    """Handle the OAuth 2.0 callback, set the session cookie, and redirect home."""
    token = await _oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo") or {}
    email = user_info.get("email", "")
    if email != settings.familylink_google_email:
        raise HTTPException(status_code=403, detail="Access denied")
    response = RedirectResponse(url="/")
    response.set_cookie(
        _COOKIE_NAME,
        _make_session(email),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )
    return response


@router.get("/logout")
async def logout() -> RedirectResponse:
    """Clear the session cookie and redirect to the login page."""
    response = RedirectResponse(url="/auth/login")
    response.delete_cookie(_COOKIE_NAME, httponly=True, secure=True, samesite="lax")
    return response
