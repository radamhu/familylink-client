# OAuth Bearer Auth + Session Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace cookie-based Family Link auth with Google OAuth Bearer tokens + stored refresh_token, add a 30-minute health-check loop that alerts Discord on session expiry, and add a "Reconnect Google Session" button to the 503 error page so parents can re-auth from any browser including mobile — no CLI, no Coolify restart needed.

**Architecture:** A new `OAuthToken` DB row stores the parent's refresh_token after their first Google OAuth login via `/auth/reauth`. `FamilyLinkService` auto-refreshes the access_token before each API call. A background `health_check_loop` detects failures and posts Discord alerts. The 503 page gains a Reconnect button that re-triggers the OAuth flow. Cookie-based auth remains as fallback so existing deployments keep working.

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy async + asyncpg, Alembic, httpx, authlib, discord.py, pytest (asyncio_mode=auto)

## Global Constraints

- Python 3.12 — no `uv`, use `pip` and `python -m pytest`
- Run `ruff check src tests && ruff format src tests` before every commit
- Tests in `tests/unit/` (no DB, no server) or `tests/server/` (DB + FastAPI)
- `tests/server/conftest.py` sets env vars before app import — never import server modules at module level in test files without this running first
- `asyncio_mode = "auto"` — `async def test_*` functions are awaited automatically; no `@pytest.mark.asyncio` decorator needed
- DB is async SQLAlchemy; session context manager: `async with make_session() as session:`
- `FamilyLinkService.__init__` calls `FamilyLink()` which reads env vars — tests bypass it with `FamilyLinkService.__new__(FamilyLinkService)` and set attributes manually (follow existing pattern in `test_family_link_service.py`)
- When testing anything that imports `familylink_server.main`, patch `init_service` and `setup_service_oauth` to avoid real auth (follow pattern in `test_main.py`)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `src/familylink/client.py` | Add `oauth_token` param; Bearer auth mode |
| Modify | `src/familylink_server/db/models.py` | Add `OAuthToken` model |
| Create | `alembic/versions/<rev>_add_oauth_tokens_table.py` | DB migration |
| Modify | `src/familylink_server/services/family_link.py` | Token lifecycle: expiry check, auto-refresh, `reinit_with_token`, `auth_failed` flag |
| Modify | `src/familylink_server/auth/oauth.py` | Add `/auth/reauth` route; capture refresh_token in callback |
| Modify | `src/familylink_server/main.py` | Add `setup_service_oauth` call in lifespan; `health_check_loop`; updated 503 HTML |
| Modify | `src/familylink_server/services/discord_notifier.py` | Add `notify_session_expired()` and `notify_session_restored()` |
| Modify | `src/familylink_server/routers/dashboard.py` | Pass `auth_failed` to template context |
| Modify | `src/familylink_server/templates/base.html` | Auth status banner in `<header>` |
| Create | `tests/unit/test_bearer_client.py` | FamilyLink Bearer mode unit tests |
| Create | `tests/server/test_oauth_token_model.py` | OAuthToken DB model tests |
| Create | `tests/server/test_token_lifecycle.py` | FamilyLinkService token auto-refresh tests |
| Create | `tests/server/test_reauth_route.py` | `/auth/reauth` route tests |
| Create | `tests/server/test_health_check.py` | `health_check_loop` tests |
| Create | `tests/server/test_discord_session_alerts.py` | Discord session alert method tests |

---

### Task 1: PoC — Validate Bearer Token Against the Family Link API

**This task is a gate.** If the API returns 200, proceed with Tasks 2–7. If 401/403, stop and implement the Fallback B path from the spec (iOS Shortcut + cookie hot-reload endpoint) instead of Tasks 2–7.

**Files:**
- Temporarily modify (revert after test): `src/familylink_server/auth/oauth.py`

- [ ] **Step 1: Add a temporary log line to the OAuth callback**

In `src/familylink_server/auth/oauth.py`, add at the top of the file if not already present:
```python
import logging
logger = logging.getLogger(__name__)
```

In the `callback` function, immediately after `token = await _oauth.google.authorize_access_token(request)`, add:
```python
logger.warning("POC_ACCESS_TOKEN: %s", (token.get("access_token") or "")[:120])
```

- [ ] **Step 2: Run the dev server and capture a token**

```bash
source .venv/bin/activate
uvicorn familylink_server.main:app --reload
```

Open `http://localhost:8000` in your browser. Log in with the parent Google account. Copy the `ya29.*` value printed in the terminal after `POC_ACCESS_TOKEN:`.

- [ ] **Step 3: Test Bearer auth against the Family Link API**

```bash
TOKEN="ya29.PASTE_YOUR_TOKEN_HERE"
curl -s -w "\nHTTP_STATUS:%{http_code}" \
  "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/families/mine/members" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json+protobuf" \
  -H "Origin: https://familylink.google.com"
```

**Expected on success:** response body with family member data and `HTTP_STATUS:200`

**If you get 401 or 403:** Bearer tokens do not work for this API. Stop here. Implement Fallback B from the spec instead (cookie hot-reload endpoint + iOS Shortcut). Tasks 2–7 below assume this PoC passed.

- [ ] **Step 4: Remove the temporary log line**

Delete the `logger.warning("POC_ACCESS_TOKEN: ...")` line from `auth/oauth.py`.

---

### Task 2: OAuthToken DB Model + Alembic Migration

**Files:**
- Modify: `src/familylink_server/db/models.py`
- Create: `alembic/versions/<rev>_add_oauth_tokens_table.py`
- Create: `tests/server/test_oauth_token_model.py`

**Interfaces:**
- Produces: `OAuthToken` SQLAlchemy model with fields `email`, `refresh_token`, `access_token`, `token_expiry`, `updated_at`

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_oauth_token_model.py`:

```python
"""Tests for OAuthToken DB model."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from familylink_server.db.models import OAuthToken
from familylink_server.db.session import make_session


async def test_oauth_token_roundtrip():
    expiry = datetime.now(UTC) + timedelta(hours=1)
    async with make_session() as session:
        row = OAuthToken(
            email="parent@example.com",
            refresh_token="1//test_refresh",
            access_token="ya29.test_access",
            token_expiry=expiry,
            updated_at=datetime.now(UTC),
        )
        session.add(row)
        await session.commit()

        result = await session.execute(
            select(OAuthToken).where(OAuthToken.email == "parent@example.com")
        )
        retrieved = result.scalar_one()
        assert retrieved.refresh_token == "1//test_refresh"
        assert retrieved.access_token == "ya29.test_access"

    # Cleanup
    async with make_session() as session:
        result = await session.execute(
            select(OAuthToken).where(OAuthToken.email == "parent@example.com")
        )
        row = result.scalar_one_or_none()
        if row:
            await session.delete(row)
            await session.commit()


async def test_oauth_token_email_unique():
    async with make_session() as session:
        row1 = OAuthToken(
            email="unique@example.com",
            refresh_token="refresh1",
            updated_at=datetime.now(UTC),
        )
        session.add(row1)
        await session.commit()

        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            row2 = OAuthToken(
                email="unique@example.com",
                refresh_token="refresh2",
                updated_at=datetime.now(UTC),
            )
            session.add(row2)
            await session.commit()

    # Cleanup
    async with make_session() as session:
        result = await session.execute(
            select(OAuthToken).where(OAuthToken.email == "unique@example.com")
        )
        row = result.scalar_one_or_none()
        if row:
            await session.delete(row)
            await session.commit()
```

- [ ] **Step 2: Run test — expect failure (table does not exist)**

```bash
python -m pytest tests/server/test_oauth_token_model.py -v
```

Expected: error about missing `oauth_tokens` table.

- [ ] **Step 3: Add OAuthToken to `db/models.py`**

Add after the last existing model class (`LinuxUsageSnapshot`) in `src/familylink_server/db/models.py`:

```python
class OAuthToken(Base):
    """Stored Google OAuth refresh_token for Bearer-token auth."""

    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 4: Generate and apply the Alembic migration**

```bash
alembic revision --autogenerate -m "add oauth_tokens table"
alembic upgrade head
```

Open the generated file in `alembic/versions/`. Verify it has `op.create_table('oauth_tokens', ...)` with all five columns. Fix manually if autogenerate missed anything.

- [ ] **Step 5: Run test — expect pass**

```bash
python -m pytest tests/server/test_oauth_token_model.py -v
```

Expected: both tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/db/models.py alembic/versions/ tests/server/test_oauth_token_model.py
git commit -m "feat: add OAuthToken model and migration"
```

---

### Task 3: FamilyLink Client Bearer Auth Mode

**Files:**
- Modify: `src/familylink/client.py`
- Create: `tests/unit/test_bearer_client.py`

**Interfaces:**
- Produces: `FamilyLink(oauth_token="ya29.xxx")` — constructs client using `Authorization: Bearer {token}`, no cookies, no API key

- [ ] **Step 1: Write the failing tests**

Install `respx` if not already present: `pip install respx`

Create `tests/unit/test_bearer_client.py`:

```python
"""Tests for FamilyLink client Bearer auth mode."""
import httpx
import pytest
import respx

from familylink.client import FamilyLink, SessionExpiredError

_MEMBERS_URL = (
    "https://kidsmanagement-pa.clients6.google.com"
    "/kidsmanagement/v1/families/mine/members"
)


@respx.mock
def test_bearer_mode_sends_bearer_header():
    route = respx.get(_MEMBERS_URL).mock(return_value=httpx.Response(200, json=[]))

    client = FamilyLink(oauth_token="ya29.test_token")
    try:
        client.get_members()
    except Exception:
        pass  # parser may fail on empty list — only the header matters

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer ya29.test_token"


@respx.mock
def test_bearer_mode_omits_api_key():
    route = respx.get(_MEMBERS_URL).mock(return_value=httpx.Response(200, json=[]))

    client = FamilyLink(oauth_token="ya29.test_token")
    try:
        client.get_members()
    except Exception:
        pass

    assert "x-goog-api-key" not in route.calls.last.request.headers


@respx.mock
def test_bearer_mode_omits_cookies():
    route = respx.get(_MEMBERS_URL).mock(return_value=httpx.Response(200, json=[]))

    client = FamilyLink(oauth_token="ya29.test_token")
    try:
        client.get_members()
    except Exception:
        pass

    assert not route.calls.last.request.headers.get("cookie", "")


@respx.mock
def test_bearer_mode_raises_session_expired_on_401():
    respx.get(_MEMBERS_URL).mock(return_value=httpx.Response(401))

    client = FamilyLink(oauth_token="ya29.test_token")
    with pytest.raises(SessionExpiredError):
        client.get_members()


def test_cookie_mode_unchanged_when_no_oauth_token(monkeypatch):
    """Existing SAPISIDHASH path is intact when oauth_token is not passed."""
    monkeypatch.setenv("FAMILYLINK_SAPISID", "test_sapisid_value")
    client = FamilyLink()
    assert client._headers["authorization"].startswith("SAPISIDHASH ")
    assert "x-goog-api-key" in client._headers
```

- [ ] **Step 2: Run tests — expect failure**

```bash
python -m pytest tests/unit/test_bearer_client.py -v
```

Expected: FAILED — `FamilyLink` does not accept `oauth_token` yet.

- [ ] **Step 3: Add Bearer mode to `client.py`**

In `src/familylink/client.py`, change `FamilyLink.__init__` to:

```python
def __init__(
    self,
    account_id: str | None = None,
    browser: str = "firefox",
    cookie_file_path: Path | None = None,
    oauth_token: str | None = None,
) -> None:
    self.account_id = account_id

    if oauth_token:
        self._headers = {
            "User-Agent": "Mozilla/5.0",
            "Origin": self.ORIGIN,
            "Content-Type": "application/json+protobuf",
            "Authorization": f"Bearer {oauth_token}",
        }
        self._cookies = None
    else:
        sapisid, cookies_jar = CookieResolver(browser, cookie_file_path).resolve()
        self._headers = {
            "User-Agent": "Mozilla/5.0",
            "Origin": self.ORIGIN,
            "Content-Type": "application/json+protobuf",
            "X-Goog-Api-Key": "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw",
            "Authorization": f"SAPISIDHASH {_generate_sapisidhash(sapisid, self.ORIGIN)}",
        }
        self._cookies = cookies_jar

    self._session = httpx.Client(
        headers=self._headers, cookies=self._cookies, timeout=30
    )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/unit/test_bearer_client.py -v
```

Expected: all 5 tests PASSED.

- [ ] **Step 5: Verify no regressions**

```bash
python -m pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/familylink/client.py tests/unit/test_bearer_client.py
git commit -m "feat: add Bearer token auth mode to FamilyLink client"
```

---

### Task 4: FamilyLinkService OAuth Token Lifecycle

**Files:**
- Modify: `src/familylink_server/services/family_link.py`
- Create: `tests/server/test_token_lifecycle.py`

**Interfaces:**
- Consumes: `FamilyLink(oauth_token=...)` from Task 3; `OAuthToken` from Task 2; `make_session()` from `db/session.py`
- Produces:
  - `FamilyLinkService.auth_failed: bool` — read-only property
  - `FamilyLinkService.set_auth_failed(failed: bool) -> None`
  - `FamilyLinkService.reinit_with_token(db_session: AsyncSession, refresh_token: str) -> None`
  - `setup_service_oauth(db_session: AsyncSession) -> None` — module-level, upgrades to Bearer mode if DB row exists

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_token_lifecycle.py`:

```python
"""Tests for FamilyLinkService OAuth token lifecycle."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from familylink_server.services.family_link import FamilyLinkService


def _make_service():
    """Create a service instance bypassing __init__ (avoids FamilyLink() cookie lookup)."""
    svc = FamilyLinkService.__new__(FamilyLinkService)
    svc._ttl = 0
    svc._members_cache = None
    svc._usage_cache = {}
    svc._refresh_token = None
    svc._access_token = None
    svc._token_expiry = None
    svc._auth_failed = False
    svc._client = MagicMock()
    return svc


async def test_auth_failed_starts_false():
    svc = _make_service()
    assert svc.auth_failed is False


async def test_set_auth_failed():
    svc = _make_service()
    svc.set_auth_failed(True)
    assert svc.auth_failed is True
    svc.set_auth_failed(False)
    assert svc.auth_failed is False


async def test_token_needs_refresh_when_no_token():
    svc = _make_service()
    svc._refresh_token = "1//test"
    svc._access_token = None
    assert svc._token_needs_refresh() is True


async def test_token_needs_refresh_when_expired():
    svc = _make_service()
    svc._refresh_token = "1//test"
    svc._access_token = "ya29.old"
    svc._token_expiry = datetime.now(UTC) - timedelta(seconds=10)
    assert svc._token_needs_refresh() is True


async def test_token_fresh_when_not_expired():
    svc = _make_service()
    svc._refresh_token = "1//test"
    svc._access_token = "ya29.current"
    svc._token_expiry = datetime.now(UTC) + timedelta(hours=1)
    assert svc._token_needs_refresh() is False


async def test_refresh_access_token_calls_google():
    svc = _make_service()
    svc._refresh_token = "1//myrefresh"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "ya29.new", "expires_in": 3599}
    mock_resp.raise_for_status = MagicMock()

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_http):
        token = await svc._refresh_access_token()

    assert token == "ya29.new"
    assert svc._access_token == "ya29.new"
    assert svc._token_expiry > datetime.now(UTC)


async def test_reinit_with_token_switches_to_bearer():
    svc = _make_service()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "ya29.fresh", "expires_in": 3599}
    mock_resp.raise_for_status = MagicMock()
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    with (
        patch("httpx.AsyncClient", return_value=mock_http),
        patch("familylink_server.services.family_link.FamilyLink") as MockClient,
    ):
        await svc.reinit_with_token(mock_db, "1//new_refresh")

    MockClient.assert_called_with(oauth_token="ya29.fresh")
    assert svc._refresh_token == "1//new_refresh"
    assert svc._auth_failed is False
```

- [ ] **Step 2: Run tests — expect failure**

```bash
python -m pytest tests/server/test_token_lifecycle.py -v
```

Expected: FAILED — methods do not exist yet.

- [ ] **Step 3: Rewrite `family_link.py` with token lifecycle**

Replace the full contents of `src/familylink_server/services/family_link.py` with:

```python
"""Singleton service wrapping the FamilyLink client with async + cache-aside."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from familylink import FamilyLink
from familylink.models import AppUsage, MembersResponse
from familylink_server.config import settings
from familylink_server.db.models import OAuthToken

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_TOKEN_BUFFER = timedelta(seconds=60)


class FamilyLinkService:
    """Wraps the synchronous FamilyLink client for async FastAPI use."""

    def __init__(self) -> None:
        self._client = FamilyLink()
        self._ttl = settings.cache_ttl_seconds
        self._members_cache: tuple[MembersResponse, datetime] | None = None
        self._usage_cache: dict[str, tuple[AppUsage, datetime]] = {}
        self._refresh_token: str | None = None
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None
        self._auth_failed: bool = False

    @property
    def auth_failed(self) -> bool:
        return self._auth_failed

    def set_auth_failed(self, failed: bool) -> None:
        self._auth_failed = failed

    def _is_fresh(self, ts: datetime) -> bool:
        return (datetime.now(UTC) - ts).total_seconds() < self._ttl

    def _token_needs_refresh(self) -> bool:
        if not self._refresh_token:
            return False
        if not self._access_token or not self._token_expiry:
            return True
        return datetime.now(UTC) >= self._token_expiry - _TOKEN_BUFFER

    async def _refresh_access_token(self) -> str:
        """Exchange refresh_token for a fresh access_token via Google's token endpoint."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                },
            )
            resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = datetime.now(UTC) + timedelta(
            seconds=data.get("expires_in", 3599)
        )
        return self._access_token

    async def _ensure_bearer_token(self) -> None:
        """Refresh the token if needed and rebuild the client with the new token."""
        if not self._token_needs_refresh():
            return
        new_token = await self._refresh_access_token()
        self._client = FamilyLink(oauth_token=new_token)
        self._members_cache = None
        self._usage_cache.clear()

    async def reinit_with_token(
        self, db_session: AsyncSession, refresh_token: str
    ) -> None:
        """Store refresh_token in DB and hot-swap client to OAuth Bearer mode."""
        self._refresh_token = refresh_token
        self._access_token = None
        self._token_expiry = None
        await self._refresh_access_token()
        self._client = FamilyLink(oauth_token=self._access_token)
        self._members_cache = None
        self._usage_cache.clear()
        self._auth_failed = False

        now = datetime.now(UTC)
        result = await db_session.execute(
            select(OAuthToken).where(
                OAuthToken.email == settings.familylink_google_email
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.refresh_token = refresh_token
            row.access_token = self._access_token
            row.token_expiry = self._token_expiry
            row.updated_at = now
        else:
            db_session.add(
                OAuthToken(
                    email=settings.familylink_google_email,
                    refresh_token=refresh_token,
                    access_token=self._access_token,
                    token_expiry=self._token_expiry,
                    updated_at=now,
                )
            )
        await db_session.commit()
        logger.info("OAuth token stored; client switched to Bearer mode")

    async def _load_token_from_db(self, db_session: AsyncSession) -> bool:
        """Load stored refresh_token from DB on startup. Returns True if found."""
        result = await db_session.execute(
            select(OAuthToken).where(
                OAuthToken.email == settings.familylink_google_email
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        self._refresh_token = row.refresh_token
        self._access_token = row.access_token
        self._token_expiry = row.token_expiry
        if self._token_needs_refresh():
            try:
                await self._refresh_access_token()
            except Exception as exc:
                logger.warning("Failed to refresh token on startup: %s", exc)
                return False
        self._client = FamilyLink(oauth_token=self._access_token)
        logger.info("Loaded OAuth Bearer token from DB on startup")
        return True

    async def get_members(self) -> MembersResponse:
        if self._refresh_token:
            await self._ensure_bearer_token()
        if self._members_cache and self._is_fresh(self._members_cache[1]):
            return self._members_cache[0]
        result = await asyncio.to_thread(self._client.get_members)
        self._members_cache = (result, datetime.now(UTC))
        return result

    async def get_apps_and_usage(self, child_id: str) -> AppUsage:
        if self._refresh_token:
            await self._ensure_bearer_token()
        cached = self._usage_cache.get(child_id)
        if cached and self._is_fresh(cached[1]):
            return cached[0]
        result = await asyncio.to_thread(self._client.get_apps_and_usage, child_id)
        self._usage_cache[child_id] = (result, datetime.now(UTC))
        return result

    async def lock_device(self, device_id: str, child_id: str | None = None) -> None:
        if self._refresh_token:
            await self._ensure_bearer_token()
        await asyncio.to_thread(
            self._client.lock_device, account_id=child_id, device_id=device_id
        )

    async def unlock_device(self, device_id: str, child_id: str | None = None) -> None:
        if self._refresh_token:
            await self._ensure_bearer_token()
        await asyncio.to_thread(
            self._client.unlock_device, account_id=child_id, device_id=device_id
        )

    async def set_app_limit(
        self, package_name: str, minutes: int, child_id: str | None = None
    ) -> None:
        if self._refresh_token:
            await self._ensure_bearer_token()
        await asyncio.to_thread(self._client.set_app_limit, package_name, minutes, child_id)
        if child_id:
            self._usage_cache.pop(child_id, None)
        else:
            self._usage_cache.clear()

    async def block_app(self, package_name: str, child_id: str | None = None) -> None:
        if self._refresh_token:
            await self._ensure_bearer_token()
        await asyncio.to_thread(self._client.block_app, package_name, child_id)
        if child_id:
            self._usage_cache.pop(child_id, None)
        else:
            self._usage_cache.clear()

    async def always_allow_app(
        self, package_name: str, child_id: str | None = None
    ) -> None:
        if self._refresh_token:
            await self._ensure_bearer_token()
        await asyncio.to_thread(self._client.always_allow_app, package_name, child_id)
        if child_id:
            self._usage_cache.pop(child_id, None)
        else:
            self._usage_cache.clear()


_service: FamilyLinkService | None = None


def init_service() -> FamilyLinkService:
    """Create the singleton in cookie mode. Called synchronously in lifespan."""
    global _service
    _service = FamilyLinkService()
    return _service


async def setup_service_oauth(db_session: AsyncSession) -> None:
    """Upgrade singleton to Bearer mode if a refresh_token exists in DB.

    Called in lifespan immediately after init_service().
    """
    if _service is None:
        raise RuntimeError("Call init_service() before setup_service_oauth()")
    await _service._load_token_from_db(db_session)


def get_service() -> FamilyLinkService:
    if _service is None:
        raise RuntimeError(
            "FamilyLinkService not initialised — call init_service() in lifespan"
        )
    return _service
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/server/test_token_lifecycle.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest -v
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/services/family_link.py tests/server/test_token_lifecycle.py
git commit -m "feat: OAuth token lifecycle in FamilyLinkService (auto-refresh, reinit, auth_failed)"
```

---

### Task 5: OAuth Reauth Route + Refresh Token Capture

**Files:**
- Modify: `src/familylink_server/auth/oauth.py`
- Modify: `src/familylink_server/main.py`
- Create: `tests/server/test_reauth_route.py`

**Interfaces:**
- Consumes: `FamilyLinkService.reinit_with_token()` from Task 4; `setup_service_oauth()` from Task 4; `make_session()` from `db/session.py`
- Produces: `GET /auth/reauth` — redirects to Google OAuth with `access_type=offline&prompt=consent`; updated `GET /auth/callback` that stores refresh_token and calls `reinit_with_token()`

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_reauth_route.py`:

```python
"""Tests for /auth/reauth route."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with patch("familylink_server.main.init_service"), \
         patch("familylink_server.main.setup_service_oauth", new=AsyncMock()):
        from familylink_server.main import app
        return TestClient(app, raise_server_exceptions=False)


def test_reauth_redirects_to_google(client):
    mock_redirect = RedirectResponse(
        url="https://accounts.google.com/o/oauth2/auth?access_type=offline&prompt=consent",
        status_code=302,
    )
    with patch(
        "familylink_server.auth.oauth._oauth.google.authorize_redirect",
        new=AsyncMock(return_value=mock_redirect),
    ) as mock_redirect_fn:
        resp = client.get("/auth/reauth", follow_redirects=False)

    assert resp.status_code in (302, 307)
    _, call_kwargs = mock_redirect_fn.call_args
    assert call_kwargs.get("access_type") == "offline"
    assert call_kwargs.get("prompt") == "consent"


def test_reauth_route_is_registered(client):
    paths = list(client.app.openapi()["paths"].keys())
    assert "/auth/reauth" in paths
```

- [ ] **Step 2: Run tests — expect failure**

```bash
python -m pytest tests/server/test_reauth_route.py -v
```

Expected: FAILED — `/auth/reauth` does not exist yet.

- [ ] **Step 3: Add `/auth/reauth` and update `callback` in `auth/oauth.py`**

At the top of `src/familylink_server/auth/oauth.py`, add these imports:

```python
import logging
from familylink_server.db.session import make_session
from familylink_server.services.family_link import get_service

logger = logging.getLogger(__name__)
```

Add the new route (after the existing `/auth/login` route):

```python
@router.get("/reauth")
async def reauth(request: Request) -> RedirectResponse:
    """Trigger Google OAuth with offline access to capture a refresh_token."""
    redirect_uri = str(request.url_for("auth_callback"))
    return await _oauth.google.authorize_redirect(
        request,
        redirect_uri,
        access_type="offline",
        prompt="consent",
    )
```

Update the existing `callback` function to capture and store the refresh_token. Replace the existing `callback` body with:

```python
@router.get("/callback", name="auth_callback")
async def callback(request: Request) -> RedirectResponse:
    """Handle OAuth callback; set session cookie; store refresh_token if present."""
    token = await _oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo") or {}
    email = user_info.get("email", "")
    if email != settings.familylink_google_email:
        raise HTTPException(status_code=403, detail="Access denied")

    refresh_token = token.get("refresh_token")
    if refresh_token:
        try:
            async with make_session() as db_session:
                await get_service().reinit_with_token(db_session, refresh_token)
            logger.info("refresh_token stored; service switched to Bearer mode")
        except Exception as exc:
            logger.warning("Failed to store refresh_token: %s", exc)

    response = RedirectResponse(url="/")
    response.set_cookie(
        _COOKIE_NAME,
        _make_session(email),
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return response
```

- [ ] **Step 4: Call `setup_service_oauth` in `main.py` lifespan**

In `src/familylink_server/main.py`, update the import line for family_link:

```python
from familylink_server.services.family_link import get_service, init_service, setup_service_oauth
```

In the `lifespan` function, after `init_service()` and after the `_make_session` import, add:

```python
async with _make_session() as _db_session:
    await setup_service_oauth(_db_session)
```

The start of `lifespan` should look like:

```python
@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    init_service()

    from familylink_server.db.session import make_session as _make_session

    async with _make_session() as _db_session:
        await setup_service_oauth(_db_session)

    notifier = None
    # ... rest of lifespan unchanged
```

- [ ] **Step 5: Run tests — expect pass**

```bash
python -m pytest tests/server/test_reauth_route.py -v
```

Expected: PASSED.

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest -v
```

Expected: all pass. If `test_main.py` tests fail because `setup_service_oauth` is not mocked, add `patch("familylink_server.main.setup_service_oauth", new=AsyncMock())` to the fixtures in `test_main.py` that use the lifespan.

- [ ] **Step 7: Commit**

```bash
git add src/familylink_server/auth/oauth.py src/familylink_server/main.py tests/server/test_reauth_route.py
git commit -m "feat: add /auth/reauth route and capture refresh_token in OAuth callback"
```

---

### Task 6: Health Check Loop + Discord Session Alerts

**Files:**
- Modify: `src/familylink_server/services/discord_notifier.py`
- Modify: `src/familylink_server/main.py`
- Create: `tests/server/test_discord_session_alerts.py`
- Create: `tests/server/test_health_check.py`

**Interfaces:**
- Consumes: `FamilyLinkService.get_members()`, `FamilyLinkService.set_auth_failed()` from Task 4; `DiscordNotifier` (existing)
- Produces:
  - `DiscordNotifier.notify_session_expired() -> None`
  - `DiscordNotifier.notify_session_restored() -> None`
  - `health_check_loop(service, notifier, interval=1800) -> None` coroutine in `main.py`

- [ ] **Step 1: Write Discord alert tests**

Create `tests/server/test_discord_session_alerts.py`:

```python
"""Tests for Discord session expired/restored alert methods."""
from unittest.mock import AsyncMock

import discord
import pytest

from familylink_server.services.discord_notifier import DiscordNotifier


@pytest.fixture
def notifier():
    return DiscordNotifier(channel_id=123)


@pytest.fixture
def channel():
    ch = AsyncMock(spec=discord.TextChannel)
    ch.name = "family-alerts"
    return ch


async def test_notify_session_expired_posts_embed(notifier, channel):
    notifier.set_channel(channel)
    await notifier.notify_session_expired()
    channel.send.assert_awaited_once()
    embed = channel.send.call_args.kwargs["embed"]
    assert "expired" in embed.title.lower()


async def test_notify_session_restored_posts_embed(notifier, channel):
    notifier.set_channel(channel)
    await notifier.notify_session_restored()
    channel.send.assert_awaited_once()
    embed = channel.send.call_args.kwargs["embed"]
    assert "restored" in embed.title.lower()


async def test_session_alerts_noop_without_channel(notifier):
    """Both methods are silent no-ops when the Discord channel is not yet set."""
    await notifier.notify_session_expired()
    await notifier.notify_session_restored()
```

- [ ] **Step 2: Write health check loop tests**

Create `tests/server/test_health_check.py`:

```python
"""Tests for health_check_loop background task."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from familylink import SessionExpiredError
from familylink_server.main import health_check_loop


def _make_service(*, fail=False):
    svc = MagicMock()
    svc.auth_failed = False
    svc.set_auth_failed = MagicMock()
    if fail:
        svc.get_members = AsyncMock(side_effect=SessionExpiredError("expired"))
    else:
        svc.get_members = AsyncMock(return_value=MagicMock())
    return svc


async def test_health_check_alerts_on_first_failure():
    svc = _make_service(fail=True)
    notifier = AsyncMock()

    sleep_count = 0
    async def mock_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", new=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            await health_check_loop(svc, notifier, interval=0)

    notifier.notify_session_expired.assert_awaited_once()
    svc.set_auth_failed.assert_called_with(True)


async def test_health_check_no_duplicate_alerts():
    svc = _make_service(fail=True)
    notifier = AsyncMock()

    sleep_count = 0
    async def mock_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 4:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", new=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            await health_check_loop(svc, notifier, interval=0)

    assert notifier.notify_session_expired.await_count == 1


async def test_health_check_restored_alert_on_recovery():
    svc = MagicMock()
    svc.auth_failed = False
    svc.set_auth_failed = MagicMock()
    notifier = AsyncMock()

    call_count = 0
    async def get_members_side():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise SessionExpiredError("expired")

    svc.get_members = get_members_side

    sleep_count = 0
    async def mock_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 4:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", new=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            await health_check_loop(svc, notifier, interval=0)

    notifier.notify_session_expired.assert_awaited_once()
    notifier.notify_session_restored.assert_awaited_once()


async def test_health_check_noop_when_notifier_is_none():
    svc = _make_service(fail=True)

    sleep_count = 0
    async def mock_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", new=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            await health_check_loop(svc, notifier=None, interval=0)
```

- [ ] **Step 3: Run tests — expect failure**

```bash
python -m pytest tests/server/test_discord_session_alerts.py tests/server/test_health_check.py -v
```

Expected: FAILED — methods and function don't exist yet.

- [ ] **Step 4: Add `notify_session_expired` and `notify_session_restored` to `discord_notifier.py`**

In `src/familylink_server/services/discord_notifier.py`, add to the `DiscordNotifier` class (after `post_daily_summary`):

```python
async def notify_session_expired(self) -> None:
    """Post a session-expired alert. No-op if channel not ready."""
    if self._channel is None:
        return
    embed = discord.Embed(
        title="⚠️ Google session expired",
        description=(
            "Family Link cookies have expired. "
            "Open the web UI and tap **Reconnect Google Session** to restore access."
        ),
        color=discord.Color.red(),
    )
    await self._channel.send(embed=embed)

async def notify_session_restored(self) -> None:
    """Post a session-restored confirmation. No-op if channel not ready."""
    if self._channel is None:
        return
    embed = discord.Embed(
        title="✅ Family Link session restored",
        description="The Google session is active again. All features are back online.",
        color=discord.Color.green(),
    )
    await self._channel.send(embed=embed)
```

- [ ] **Step 5: Add `health_check_loop` to `main.py`**

In `src/familylink_server/main.py`, add this function before the `lifespan` definition:

```python
async def health_check_loop(
    service: "FamilyLinkService",
    notifier: "DiscordNotifier | None",
    interval: int = 1800,
) -> None:
    """Probe the Family Link API every `interval` seconds; alert Discord on failure."""
    from familylink import SessionExpiredError

    _alert_active = False
    while True:
        await asyncio.sleep(interval)
        try:
            await service.get_members()
            if _alert_active:
                _alert_active = False
                service.set_auth_failed(False)
                if notifier:
                    await notifier.notify_session_restored()
        except (SessionExpiredError, Exception) as exc:
            logger.warning("Health check failed: %s", exc)
            if not _alert_active:
                _alert_active = True
                service.set_auth_failed(True)
                if notifier:
                    await notifier.notify_session_expired()
```

In the `lifespan` function, after the existing `poller_task = asyncio.create_task(...)` line, add:

```python
health_task = asyncio.create_task(health_check_loop(get_service(), notifier))
logger.info("Health check task started")
```

In the cleanup section (after `poller_task.cancel()`), add:

```python
health_task.cancel()
with contextlib.suppress(asyncio.CancelledError):
    await health_task
```

- [ ] **Step 6: Run tests — expect pass**

```bash
python -m pytest tests/server/test_discord_session_alerts.py tests/server/test_health_check.py -v
```

Expected: all PASSED.

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/familylink_server/services/discord_notifier.py src/familylink_server/main.py \
    tests/server/test_discord_session_alerts.py tests/server/test_health_check.py
git commit -m "feat: health check loop and Discord session expired/restored alerts"
```

---

### Task 7: 503 Page Reconnect Button + Dashboard Auth Banner

**Files:**
- Modify: `src/familylink_server/main.py` (503 HTML)
- Modify: `src/familylink_server/routers/dashboard.py`
- Modify: `src/familylink_server/templates/base.html`

**Interfaces:**
- Consumes: `FamilyLinkService.auth_failed` from Task 4; `/auth/reauth` route from Task 5

- [ ] **Step 1: Update the 503 page HTML in `main.py`**

Find the `session_expired_handler` function in `src/familylink_server/main.py`. Replace the `content="""..."""` string with:

```python
content="""<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Session Expired — Family Link</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
</head>
<body>
  <main class="container" style="max-width:600px;margin-top:4rem">
    <article>
      <header><strong>Google session expired</strong></header>
      <p>The Family Link session has expired. Tap the button below to reconnect — works on mobile, no restart needed.</p>
      <a href="/auth/reauth" role="button">Reconnect Google Session</a>
      <hr>
      <details>
        <summary>Desktop fallback (CLI)</summary>
        <p>Run on your Mac then restart the deployment:</p>
        <pre>familylink export-cookies --browser chrome --base64 --coolify --restart</pre>
      </details>
    </article>
  </main>
</body>
</html>""",
```

- [ ] **Step 2: Pass `auth_failed` to the dashboard template**

In `src/familylink_server/routers/dashboard.py`, find the `templates.TemplateResponse(...)` call at the bottom of the `dashboard` function. Add `auth_failed` to the context dict:

```python
return templates.TemplateResponse(
    request,
    "dashboard.html",
    {
        "children": child_data,
        "auth_failed": svc.auth_failed,
    },
)
```

- [ ] **Step 3: Add the auth banner to `base.html`**

In `src/familylink_server/templates/base.html`, add the banner block inside `<main class="container">`, immediately before `{% block content %}`:

```html
  <main class="container">
    {% if auth_failed %}
    <div style="background:#fee2e2;border:1px solid #fca5a5;border-radius:6px;padding:0.5rem 1rem;margin-bottom:1rem;color:#991b1b">
      ⚠️ Google session expired —
      <a href="/auth/reauth">Reconnect Google Session</a>
    </div>
    {% endif %}
    {% block content %}{% endblock %}
  </main>
```

- [ ] **Step 4: Smoke test manually**

```bash
uvicorn familylink_server.main:app --reload
```

1. Open `http://localhost:8000` — verify no red banner (normal state, `auth_failed=False`).
2. In a Python shell or by temporarily setting `_service._auth_failed = True` via a debug route, reload the dashboard — verify the red banner appears with the Reconnect link.
3. Navigate to `/auth/reauth` directly — verify it redirects to Google OAuth.
4. To test the 503 page: temporarily add `raise SessionExpiredError("test")` at the top of the dashboard route, load `/`, verify the page shows the Reconnect button. Remove the line afterward.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/main.py src/familylink_server/routers/dashboard.py \
    src/familylink_server/templates/base.html
git commit -m "feat: 503 page Reconnect button and dashboard auth status banner"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| PoC gate — validate Bearer token | Task 1 |
| `OAuthToken` DB model | Task 2 |
| Alembic migration | Task 2 |
| `FamilyLink(oauth_token=...)` Bearer mode | Task 3 |
| No API key in Bearer mode | Task 3 |
| Token auto-refresh before API calls | Task 4 |
| `reinit_with_token()` hot-swap | Task 4 |
| `auth_failed` flag + `set_auth_failed()` | Task 4 |
| `setup_service_oauth()` loads token on startup | Task 4 |
| `/auth/reauth` route with `access_type=offline` + `prompt=consent` | Task 5 |
| Callback stores refresh_token + reinits service | Task 5 |
| `setup_service_oauth` called in lifespan | Task 5 |
| `health_check_loop` every 30 minutes | Task 6 |
| Discord alert on session expiry | Task 6 |
| Discord alert on session recovery | Task 6 |
| No duplicate alerts while still broken | Task 6 |
| 503 page Reconnect button | Task 7 |
| Dashboard auth status banner | Task 7 |
| Backward compat (cookie mode unchanged) | Task 3 (cookie path retained), Task 4 (init_service cookie-first) |
| Linux machines hold last known state | No task — existing poller behaviour is unchanged |
| Fallback B (iOS Shortcut) | Conditional on Task 1 PoC failing — documented in spec only |

**No gaps.**

**Placeholder scan:** No TBDs, no "add validation" hand-waves, all code steps are complete.

**Type consistency:**
- `FamilyLink(oauth_token=str)` — defined Task 3, used Task 4 ✓
- `reinit_with_token(db_session: AsyncSession, refresh_token: str)` — defined Task 4, called Task 5 ✓
- `setup_service_oauth(db_session: AsyncSession)` — defined Task 4, called Task 5 lifespan ✓
- `health_check_loop(service, notifier, interval=1800)` — defined Task 6 impl, matches Task 6 tests ✓
- `notify_session_expired()` / `notify_session_restored()` — defined Task 6, tested Task 6 ✓
- `auth_failed: bool` / `set_auth_failed(bool)` — defined Task 4, used Task 6 + Task 7 ✓
