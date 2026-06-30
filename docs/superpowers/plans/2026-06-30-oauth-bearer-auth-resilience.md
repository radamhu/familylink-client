# Cookie Hot-Reload + Session Resilience — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 30-minute health-check loop that alerts Discord on session expiry, allow parents to hot-swap fresh Google cookies from any browser (no Coolify restart) via a protected web endpoint + SAPISID paste form on the 503 page, and show an auth-failure banner on the dashboard.

**Architecture:** `FamilyLinkService` gains `reinit_with_cookies(sapisid)` and `auth_failed` flag. A new `POST /admin/refresh-cookies` endpoint (protected by the existing `require_user` dep) lets the parent paste a fresh SAPISID from the 503 error page — no CLI, no restart. A background `health_check_loop` probes the API every 30 minutes and fires Discord alerts on expiry and recovery. `FamilyLink` client auth remains cookie/SAPISIDHASH based throughout.

**Note:** Task 1 (Bearer token PoC) is complete — the API returned 401, confirming Bearer tokens do not work. This plan implements the Fallback B path from the spec.

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy async + asyncpg, discord.py, pytest (asyncio_mode=auto)

## Global Constraints

- Python 3.12 — no `uv`, use `pip` and `python -m pytest`
- Run `ruff check src tests && ruff format src tests` before every commit
- Tests in `tests/unit/` (no DB, no server) or `tests/server/` (DB + FastAPI)
- `tests/server/conftest.py` sets env vars before app import — never import server modules at module level in test files without this running first
- `asyncio_mode = "auto"` — `async def test_*` functions are awaited automatically; no `@pytest.mark.asyncio` decorator needed
- DB is async SQLAlchemy; session context manager: `async with make_session() as session:`
- `FamilyLinkService.__init__` calls `FamilyLink()` which reads env vars — tests bypass it with `FamilyLinkService.__new__(FamilyLinkService)` and set attributes manually (follow existing pattern in `test_family_link_service.py`)
- Do NOT add `oauth_token` parameter to `FamilyLink` client — Bearer auth is not used

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `src/familylink_server/services/family_link.py` | Add `reinit_with_cookies()`, `auth_failed`, `set_auth_failed()` |
| Create | `src/familylink_server/routers/admin.py` | `POST /admin/refresh-cookies` endpoint |
| Modify | `src/familylink_server/main.py` | Register admin router; add `health_check_loop`; update 503 HTML |
| Modify | `src/familylink_server/services/discord_notifier.py` | Add `notify_session_expired()`, `notify_session_restored()` |
| Modify | `src/familylink_server/routers/dashboard.py` | Pass `auth_failed` to template context |
| Modify | `src/familylink_server/templates/base.html` | Auth status banner in header |
| Create | `tests/server/test_cookie_hotreload.py` | Hot-reload endpoint + service tests |
| Create | `tests/server/test_discord_session_alerts.py` | Discord alert method tests |
| Create | `tests/server/test_health_check.py` | `health_check_loop` tests |

---

### Task 1: PoC Gate (COMPLETE)

Bearer token returned HTTP 401 — the `kidsmanagement-pa` API only accepts SAPISIDHASH auth.
Log line removed from `auth/oauth.py`. Proceeding with Fallback B.

---

### Task 2: Cookie Hot-Reload — Service + Endpoint + `auth_failed`

**Files:**
- Modify: `src/familylink_server/services/family_link.py`
- Create: `src/familylink_server/routers/admin.py`
- Modify: `src/familylink_server/main.py` (register router only — `health_check_loop` in Task 3)
- Create: `tests/server/test_cookie_hotreload.py`

**Interfaces:**
- Produces:
  - `FamilyLinkService.reinit_with_cookies(sapisid: str) -> None`
  - `FamilyLinkService.auth_failed: bool` property
  - `FamilyLinkService.set_auth_failed(failed: bool) -> None`
  - `POST /admin/refresh-cookies` — body `{"sapisid": "..."}`, requires logged-in user, returns 204

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_cookie_hotreload.py`:

```python
"""Tests for cookie hot-reload endpoint and FamilyLinkService methods."""
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from familylink_server.services.family_link import FamilyLinkService


def _make_service():
    """Create a service instance bypassing __init__ (avoids FamilyLink() cookie lookup)."""
    svc = FamilyLinkService.__new__(FamilyLinkService)
    svc._ttl = 0
    svc._members_cache = None
    svc._usage_cache = {}
    svc._auth_failed = False
    svc._client = MagicMock()
    return svc


def test_auth_failed_starts_false():
    svc = _make_service()
    assert svc.auth_failed is False


def test_set_auth_failed_true():
    svc = _make_service()
    svc.set_auth_failed(True)
    assert svc.auth_failed is True


def test_set_auth_failed_false():
    svc = _make_service()
    svc.set_auth_failed(True)
    svc.set_auth_failed(False)
    assert svc.auth_failed is False


def test_reinit_with_cookies_creates_new_client(monkeypatch):
    svc = _make_service()
    old_client = svc._client

    with patch(
        "familylink_server.services.family_link.FamilyLink"
    ) as MockFamilyLink:
        MockFamilyLink.return_value = MagicMock()
        svc.reinit_with_cookies("test_sapisid_value")

    # New client was created
    assert svc._client is not old_client
    # FAMILYLINK_SAPISID was set before creating the new client
    MockFamilyLink.assert_called_once()


def test_reinit_with_cookies_clears_caches():
    svc = _make_service()
    svc._members_cache = (MagicMock(), MagicMock())
    svc._usage_cache = {"child1": (MagicMock(), MagicMock())}
    svc._auth_failed = True

    with patch("familylink_server.services.family_link.FamilyLink"):
        svc.reinit_with_cookies("new_sapisid")

    assert svc._members_cache is None
    assert svc._usage_cache == {}
    assert svc._auth_failed is False


def test_reinit_with_cookies_sets_env_var():
    svc = _make_service()

    with patch("familylink_server.services.family_link.FamilyLink"):
        with patch.dict(os.environ, {}, clear=False):
            svc.reinit_with_cookies("MY_SAPISID_VALUE")
            assert os.environ.get("FAMILYLINK_SAPISID") == "MY_SAPISID_VALUE"


@pytest.fixture
def test_client():
    with patch("familylink_server.main.init_service"):
        from familylink_server.main import app
        return TestClient(app, raise_server_exceptions=False)


def test_refresh_cookies_requires_auth(test_client):
    resp = test_client.post(
        "/admin/refresh-cookies", json={"sapisid": "test"}
    )
    assert resp.status_code == 401


def test_refresh_cookies_accepts_sapisid(test_client):
    mock_svc = _make_service()

    with (
        patch("familylink_server.main.init_service"),
        patch(
            "familylink_server.routers.admin.get_service", return_value=mock_svc
        ),
        patch("familylink_server.services.family_link.FamilyLink"),
    ):
        from itsdangerous import URLSafeSerializer
        from familylink_server.config import settings

        signer = URLSafeSerializer(settings.secret_key, salt="fl-session")
        session_cookie = signer.dumps({"email": settings.familylink_google_email})

        resp = test_client.post(
            "/admin/refresh-cookies",
            json={"sapisid": "fresh_sapisid_value"},
            cookies={"fl_session": session_cookie},
        )

    assert resp.status_code == 204
```

- [ ] **Step 2: Run tests — expect failure**

```bash
python -m pytest tests/server/test_cookie_hotreload.py -v
```

Expected: FAILED — methods and endpoint do not exist yet.

- [ ] **Step 3: Add `reinit_with_cookies`, `auth_failed`, `set_auth_failed` to `family_link.py`**

Read the current `src/familylink_server/services/family_link.py` first.

Add `import os` at the top of the file (if not already present).

Add these three methods to the `FamilyLinkService` class (after `__init__`):

```python
@property
def auth_failed(self) -> bool:
    return self._auth_failed

def set_auth_failed(self, failed: bool) -> None:
    self._auth_failed = failed

def reinit_with_cookies(self, sapisid: str) -> None:
    """Hot-swap the FamilyLink client with a fresh SAPISID. No restart needed."""
    os.environ["FAMILYLINK_SAPISID"] = sapisid
    self._client = FamilyLink()
    self._members_cache = None
    self._usage_cache.clear()
    self._auth_failed = False
    logger.info("FamilyLink client reinitialized with fresh SAPISID")
```

Also add `_auth_failed: bool = False` to `__init__` (after the other instance vars).

Verify `logger = logging.getLogger(__name__)` is already in the file. If not, add it after the imports.

- [ ] **Step 4: Create `src/familylink_server/routers/admin.py`**

```python
"""Admin endpoints — protected, for operational management."""
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import get_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class RefreshCookiesRequest(BaseModel):
    sapisid: str


@router.post("/refresh-cookies", status_code=204, dependencies=[require_user])
async def refresh_cookies(body: RefreshCookiesRequest) -> None:
    """Hot-swap the FamilyLink client with fresh cookies. No server restart needed."""
    get_service().reinit_with_cookies(body.sapisid)
    logger.info("Cookies hot-reloaded via /admin/refresh-cookies")
```

- [ ] **Step 5: Register the admin router in `main.py`**

In `src/familylink_server/main.py`, find the block where other routers are imported and included. Add:

```python
from familylink_server.routers.admin import router as admin_router
```

And in the `app` setup block (alongside `app.include_router(auth_router)` etc.):

```python
app.include_router(admin_router)
```

- [ ] **Step 6: Run tests — expect pass**

```bash
python -m pytest tests/server/test_cookie_hotreload.py -v
```

Expected: all tests PASSED.

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest -v
```

Expected: all existing tests pass.

- [ ] **Step 8: Lint and commit**

```bash
ruff check src tests && ruff format src tests
git add src/familylink_server/services/family_link.py \
    src/familylink_server/routers/admin.py \
    src/familylink_server/main.py \
    tests/server/test_cookie_hotreload.py
git commit -m "feat: cookie hot-reload endpoint and auth_failed flag on FamilyLinkService"
```

---

### Task 3: Health Check Loop + Discord Session Alerts

**Files:**
- Modify: `src/familylink_server/services/discord_notifier.py`
- Modify: `src/familylink_server/main.py`
- Create: `tests/server/test_discord_session_alerts.py`
- Create: `tests/server/test_health_check.py`

**Interfaces:**
- Consumes: `FamilyLinkService.get_members()`, `FamilyLinkService.set_auth_failed()` from Task 2; `DiscordNotifier` (existing)
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

Expected: FAILED — methods and `health_check_loop` don't exist yet.

- [ ] **Step 4: Add `notify_session_expired` and `notify_session_restored` to `discord_notifier.py`**

Read `src/familylink_server/services/discord_notifier.py`. Find the `DiscordNotifier` class. Add after the last existing method:

```python
async def notify_session_expired(self) -> None:
    """Post a session-expired alert. No-op if channel not ready."""
    if self._channel is None:
        return
    embed = discord.Embed(
        title='⚠️ Google session expired',
        description=(
            'Family Link cookies have expired. '
            'Open the web UI and paste a fresh SAPISID to restore access.'
        ),
        color=discord.Color.red(),
    )
    await self._channel.send(embed=embed)

async def notify_session_restored(self) -> None:
    """Post a session-restored confirmation. No-op if channel not ready."""
    if self._channel is None:
        return
    embed = discord.Embed(
        title='✅ Family Link session restored',
        description='The Google session is active again. All features are back online.',
        color=discord.Color.green(),
    )
    await self._channel.send(embed=embed)
```

Note: match the quote style of existing methods in that file (single quotes).

- [ ] **Step 5: Add `health_check_loop` to `main.py`**

Read `src/familylink_server/main.py` to find where to add. Add this function before the `lifespan` definition:

```python
async def health_check_loop(
    service: 'FamilyLinkService',
    notifier: 'DiscordNotifier | None',
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
        except Exception as exc:
            logger.warning('Health check failed: %s', exc)
            if not _alert_active:
                _alert_active = True
                service.set_auth_failed(True)
                if notifier:
                    await notifier.notify_session_expired()
```

In the `lifespan` function, find the line that creates `poller_task`. After it, add:

```python
health_task = asyncio.create_task(health_check_loop(get_service(), notifier))
logger.info('Health check task started (interval=1800s)')
```

In the cleanup section (where `poller_task.cancel()` is called), add:

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

Expected: all existing tests pass.

- [ ] **Step 8: Lint and commit**

```bash
ruff check src tests && ruff format src tests
git add src/familylink_server/services/discord_notifier.py \
    src/familylink_server/main.py \
    tests/server/test_discord_session_alerts.py \
    tests/server/test_health_check.py
git commit -m "feat: health check loop and Discord session expired/restored alerts"
```

---

### Task 4: 503 Page Cookie Paste Form + Dashboard Auth Banner

**Files:**
- Modify: `src/familylink_server/main.py` (503 HTML only)
- Modify: `src/familylink_server/routers/dashboard.py`
- Modify: `src/familylink_server/templates/base.html`

**Interfaces:**
- Consumes: `FamilyLinkService.auth_failed` from Task 2; `POST /admin/refresh-cookies` from Task 2

**Note:** This task has no new test file — the endpoint is already tested in Task 2 and the template changes require manual smoke-testing. The full suite run at the end verifies nothing is broken.

- [ ] **Step 1: Update the 503 page HTML in `main.py`**

Find the `session_expired_handler` function in `src/familylink_server/main.py`. Replace the entire `content="""..."""` string with:

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
      <p>The Family Link session has expired. Paste a fresh <code>SAPISID</code> cookie below to restore access — works from any browser, no restart needed.</p>

      <form action="/admin/refresh-cookies" method="post"
            hx-post="/admin/refresh-cookies" hx-on::after-request="window.location='/'">
        <label for="sapisid">SAPISID cookie value</label>
        <input id="sapisid" name="sapisid" type="password"
               placeholder="Paste SAPISID here" required autocomplete="off">
        <button type="submit">Reconnect</button>
      </form>

      <details style="margin-top:1rem">
        <summary>How to get your SAPISID on mobile</summary>
        <ol>
          <li>Open <strong>google.com</strong> in your phone browser (must be logged in to your Google account)</li>
          <li>Tap the address bar and type exactly:<br>
              <code>javascript:alert(document.cookie.match(/SAPISID=([^;]+)/)[1])</code></li>
          <li>Press Go — an alert box shows your SAPISID value</li>
          <li>Copy it and paste above</li>
        </ol>
      </details>

      <details>
        <summary>Desktop fallback (CLI, requires restart)</summary>
        <pre>familylink export-cookies --browser chrome --base64 --coolify --restart</pre>
      </details>
    </article>
  </main>
  <script src="https://unpkg.com/htmx.org@2/dist/htmx.min.js"></script>
</body>
</html>""",
```

**Important:** The form uses both a plain HTML `action` (works without JS) and HTMX `hx-post` (redirects to `/` on success without a full page reload). The endpoint returns 204, so HTMX fires `hx-on::after-request` which redirects. If JS is disabled, the browser follows the form action normally — but 204 won't redirect automatically in that case; the user will see a blank page. This is acceptable for this admin-level flow.

Actually: change the form to return a redirect instead of 204 so the non-JS path also works. Update `admin.py` endpoint to return `RedirectResponse("/")` on success:

In `src/familylink_server/routers/admin.py`, change the endpoint signature and return:

```python
from fastapi.responses import RedirectResponse

@router.post("/refresh-cookies", dependencies=[require_user])
async def refresh_cookies(body: RefreshCookiesRequest) -> RedirectResponse:
    """Hot-swap the FamilyLink client with fresh cookies. No server restart needed."""
    get_service().reinit_with_cookies(body.sapisid)
    logger.info("Cookies hot-reloaded via /admin/refresh-cookies")
    return RedirectResponse(url="/", status_code=303)
```

Remove `status_code=204` from the `@router.post` decorator since it's now a redirect.

Update the test in `test_cookie_hotreload.py` to expect 303 instead of 204:

```python
assert resp.status_code == 303
```

And update the form — remove the HTMX attributes since the server handles the redirect:

```html
<form action="/admin/refresh-cookies" method="post">
```

- [ ] **Step 2: Pass `auth_failed` to the dashboard template**

Read `src/familylink_server/routers/dashboard.py`. Find the `templates.TemplateResponse(...)` call. Add `auth_failed` to the context dict:

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

If the dashboard already passes other context keys (members count, etc.), add `"auth_failed": svc.auth_failed` alongside them.

- [ ] **Step 3: Add the auth banner to `base.html`**

Read `src/familylink_server/templates/base.html`. Find the `<main class="container">` tag. Add the banner immediately inside it, before `{% block content %}`:

```html
  <main class="container">
    {% if auth_failed %}
    <div style="background:#fee2e2;border:1px solid #fca5a5;border-radius:6px;padding:0.5rem 1rem;margin-bottom:1rem;color:#991b1b">
      ⚠️ Google session expired —
      <a href="/session-expired">Reconnect</a>
    </div>
    {% endif %}
    {% block content %}{% endblock %}
  </main>
```

Note: `/session-expired` doesn't exist as a route — instead link directly to the 503 instructions. Actually, the instructions page IS the 503 page which is only shown on error. Better to link to a dedicated instructions page or use the form inline.

Change the link to the paste form itself. Since the 503 page is not a real route, link to a new `GET /admin/reconnect` page:

Add to `admin.py`:

```python
from fastapi import Request
from fastapi.responses import HTMLResponse

@router.get("/reconnect", response_class=HTMLResponse)
async def reconnect_page(_email: str = require_user) -> HTMLResponse:
    """Reconnect page — shows the SAPISID paste form."""
    return HTMLResponse(content="""<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reconnect — Family Link</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
</head>
<body>
  <main class="container" style="max-width:600px;margin-top:4rem">
    <article>
      <header><strong>Reconnect Google session</strong></header>
      <form action="/admin/refresh-cookies" method="post">
        <label for="sapisid">SAPISID cookie value</label>
        <input id="sapisid" name="sapisid" type="password"
               placeholder="Paste SAPISID here" required autocomplete="off">
        <button type="submit">Reconnect</button>
      </form>
      <details style="margin-top:1rem">
        <summary>How to get your SAPISID on mobile</summary>
        <ol>
          <li>Open <strong>google.com</strong> in your phone browser (logged into your Google account)</li>
          <li>Tap the address bar and type:<br>
              <code>javascript:alert(document.cookie.match(/SAPISID=([^;]+)/)[1])</code></li>
          <li>Press Go — an alert shows your SAPISID</li>
          <li>Copy it and paste above, then tap Reconnect</li>
        </ol>
      </details>
    </article>
  </main>
</body>
</html>""")
```

Update the dashboard banner link to `/admin/reconnect`:

```html
<a href="/admin/reconnect">Reconnect</a>
```

And update the 503 page to include the same form inline (already done in Step 1).

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest -v
```

Expected: all tests pass (including the updated 303 status check).

- [ ] **Step 5: Smoke test manually**

```bash
docker compose up -d
# or: source .venv/bin/activate && uvicorn familylink_server.main:app --reload
```

1. Open `http://localhost:8000` — verify no red banner (normal state, `auth_failed=False`).
2. Navigate to `/admin/reconnect` — verify the paste form renders.
3. Force the banner by temporarily doing: in a Python shell connected to the running app, call `get_service().set_auth_failed(True)`, then reload the dashboard — verify the red banner appears.
4. In the 503 test: verify the form appears when you see the 503 page.

- [ ] **Step 6: Lint and commit**

```bash
ruff check src tests && ruff format src tests
git add src/familylink_server/main.py \
    src/familylink_server/routers/admin.py \
    src/familylink_server/routers/dashboard.py \
    src/familylink_server/templates/base.html \
    tests/server/test_cookie_hotreload.py
git commit -m "feat: 503 page SAPISID paste form, reconnect page, and dashboard auth banner"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| PoC gate — Bearer auth test | Task 1 (DONE — 401, pivoted) |
| Session expiry detected within 30 min | Task 3 (`health_check_loop`, interval=1800) |
| Discord alert on expiry | Task 3 (`notify_session_expired`) |
| Discord alert on recovery | Task 3 (`notify_session_restored`) |
| No duplicate alerts while still broken | Task 3 (`_alert_active` flag) |
| Hot-reload without restart | Task 2 (`reinit_with_cookies` + `POST /admin/refresh-cookies`) |
| Cookie renewal from any browser (mobile) | Task 4 (SAPISID paste form on 503 + reconnect page) |
| `auth_failed` flag | Task 2 (`auth_failed` property + `set_auth_failed`) |
| 503 page reconnect affordance | Task 4 (inline form on 503 page) |
| Dashboard auth status indicator | Task 4 (red banner in `base.html`) |
| Linux machines hold last known state | No task — existing poller behaviour is unchanged |
| FamilyLink cookie auth unchanged | No task — no changes to `client.py` |

**No gaps.**

**Placeholder scan:** All steps contain complete code. No TBDs.

**Type consistency:**
- `reinit_with_cookies(sapisid: str)` — defined Task 2 service, called Task 2 endpoint, called Task 4 form flow ✓
- `auth_failed: bool` / `set_auth_failed(bool)` — defined Task 2, used Task 3 health loop + Task 4 template ✓
- `health_check_loop(service, notifier, interval=1800)` — defined Task 3 impl, matches Task 3 tests ✓
- `notify_session_expired()` / `notify_session_restored()` — defined Task 3, tested Task 3 ✓
