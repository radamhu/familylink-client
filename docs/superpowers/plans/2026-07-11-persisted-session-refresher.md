# Persisted-Session Cookie Refresher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cookie-refresher sidecar's automated password+TOTP Google login (reliably blocked by Google's anti-automation detection) with a persisted-session approach: bootstrap once from a real browser via `browser_cookie3`, persist to a Docker volume, and refresh by replaying cookies through a real Playwright page load.

**Architecture:** Sidecar gains `POST /bootstrap` (writes a Playwright `storage_state` JSON to a volume path) and a rewritten `POST /refresh` (loads that state into a Playwright context, navigates to `myaccount.google.com`, extracts + persists rotated cookies). Main app gains `POST /admin/refresher-bootstrap` (X-Api-Key-protected proxy to the sidecar's `/bootstrap`). A new operator script extracts cookies from a real Chrome profile and uploads them through that proxy.

**Tech Stack:** FastAPI, Playwright (sync API, used inside `asyncio.to_thread`), `browser_cookie3`, `httpx`, pytest + `pytest-httpx` + `TestClient`.

## Global Constraints

- Ruff: single-quoted strings, Google-style docstrings, isort — run `ruff check --fix` and `ruff format` on every changed file before committing.
- TDD: write the failing test before the implementation for every behavioral change; run it and confirm the failure reason before writing code.
- No module-level env-var constants in `cookie_refresher_app.py` — read `os.environ.get(...)` inline inside each request handler / helper (matches existing style; makes tests trivial via `monkeypatch.setenv`).
- `STATE_PATH` env var, default `/data/state.json`, is the sidecar's single source of truth for the persisted session.
- `POST /admin/refresher-bootstrap` is authenticated via `X-Api-Key` against `settings.refresher_api_key`, **not** `require_user` — it's invoked by a standalone script, not a browser session.
- Do not touch `health_check_loop`, `_try_auto_refresh`, `reinit_with_cookies_b64`, or the existing manual `/admin/reconnect` flow — out of scope, already correct.
- Full test suite (`python -m pytest`) and `ruff check src tests` must stay green after every task.

---

### Task 1: Sidecar `POST /bootstrap` endpoint

**Files:**
- Modify: `src/familylink_server/cookie_refresher_app.py`
- Test: `tests/server/test_cookie_refresher.py`

**Interfaces:**
- Produces: `POST /bootstrap` on the sidecar FastAPI `app` — accepts JSON body `{"cookies": [...], "origins": [...]}` (Playwright `storage_state` shape), writes it to `Path(os.environ.get('STATE_PATH', '/data/state.json'))`, returns `204`. Requires header `X-Api-Key` matching `os.environ.get('REFRESHER_API_KEY', '')` when that env var is set (same pattern as the existing `/refresh` endpoint).

- [ ] **Step 1: Write the failing test for a successful bootstrap write**

Add to `tests/server/test_cookie_refresher.py`, after the imports at the top of the file:

```python
def test_bootstrap_writes_state_file(monkeypatch, tmp_path):
    """POST /bootstrap writes the storage_state JSON to STATE_PATH."""
    state_file = tmp_path / 'state.json'
    monkeypatch.setenv('STATE_PATH', str(state_file))
    from familylink_server.cookie_refresher_app import app

    client = TestClient(app)
    resp = client.post(
        '/bootstrap',
        json={
            'cookies': [
                {
                    'name': 'SAPISID',
                    'value': 'abc',
                    'domain': '.google.com',
                    'path': '/',
                    'expires': -1,
                    'httpOnly': False,
                    'secure': True,
                    'sameSite': 'None',
                }
            ],
            'origins': [],
        },
    )
    assert resp.status_code == 204

    import json

    saved = json.loads(state_file.read_text())
    assert saved['cookies'][0]['name'] == 'SAPISID'
    assert saved['origins'] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_cookie_refresher.py::test_bootstrap_writes_state_file -v`
Expected: FAIL with `404 Not Found` (no `/bootstrap` route exists yet) — assertion error on `resp.status_code`.

- [ ] **Step 3: Write the failing test for the wrong-API-key case**

Add directly below the previous test:

```python
def test_bootstrap_forbidden_when_wrong_key(monkeypatch, tmp_path):
    """POST /bootstrap returns 403 when REFRESHER_API_KEY is set and key is wrong."""
    monkeypatch.setenv('REFRESHER_API_KEY', 'secret')
    monkeypatch.setenv('STATE_PATH', str(tmp_path / 'state.json'))
    from familylink_server.cookie_refresher_app import app

    client = TestClient(app)
    resp = client.post(
        '/bootstrap',
        json={'cookies': [], 'origins': []},
        headers={'X-Api-Key': 'wrong'},
    )
    assert resp.status_code == 403
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/server/test_cookie_refresher.py::test_bootstrap_forbidden_when_wrong_key -v`
Expected: FAIL with `404 Not Found` — same reason, route doesn't exist.

- [ ] **Step 5: Implement `POST /bootstrap`**

In `src/familylink_server/cookie_refresher_app.py`, add these imports at the top (after `import os`):

```python
from pathlib import Path

from pydantic import BaseModel
```

So the import block reads:

```python
import asyncio
import base64
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
```

Add this class and endpoint directly after the `health()` endpoint (after line 31, before `def _get_cookies_b64`):

```python
class StorageState(BaseModel):
    """Playwright browser-context storage_state payload."""

    cookies: list[dict]
    origins: list[dict] = []


@app.post('/bootstrap', status_code=204)
async def bootstrap(body: StorageState, x_api_key: str = Header(default='')) -> None:
    """Persist a storage_state JSON to disk for /refresh to reuse."""
    expected = os.environ.get('REFRESHER_API_KEY', '')
    if expected and x_api_key != expected:
        raise HTTPException(403, 'Forbidden')

    state_path = Path(os.environ.get('STATE_PATH', '/data/state.json'))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(body.model_dump_json())
    logger.info('Bootstrap: wrote %d cookies to %s', len(body.cookies), state_path)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_cookie_refresher.py::test_bootstrap_writes_state_file tests/server/test_cookie_refresher.py::test_bootstrap_forbidden_when_wrong_key -v`
Expected: `2 passed`

- [ ] **Step 7: Lint and format**

Run: `ruff check --fix src/familylink_server/cookie_refresher_app.py tests/server/test_cookie_refresher.py && ruff format src/familylink_server/cookie_refresher_app.py tests/server/test_cookie_refresher.py`
Expected: no errors, files reported as already formatted or fixed cleanly.

- [ ] **Step 8: Commit**

```bash
git add src/familylink_server/cookie_refresher_app.py tests/server/test_cookie_refresher.py
git commit -m "feat: add POST /bootstrap to cookie-refresher sidecar"
```

---

### Task 2: Rewrite `/refresh` to replay a persisted session instead of logging in

**Files:**
- Modify: `src/familylink_server/cookie_refresher_app.py`
- Modify: `tests/server/test_cookie_refresher.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `Path(os.environ.get('STATE_PATH', '/data/state.json'))` — same convention as Task 1's `/bootstrap`.
- Produces: `_get_cookies_b64(state_path: Path) -> str` (signature change — was `_get_cookies_b64(email, password, totp_secret)`). `POST /refresh` no longer requires `FAMILYLINK_GOOGLE_EMAIL`/`PASSWORD`/`TOTP_SECRET` env vars; returns `500` with a clear message if `state_path` doesn't exist or the persisted session has expired.

This task removes the old login-flow tests (`test_refresh_missing_password`, `test_refresh_missing_totp`, `test_get_cookies_b64_raises_when_no_sapisid`, `test_get_cookies_b64_includes_page_context_on_failure`) and replaces them with equivalents for the new flow. `test_refresh_success`, `test_refresh_playwright_error`, `test_refresh_forbidden_when_wrong_key`, `test_refresh_allowed_when_key_matches` stay conceptually the same (they mock `_get_cookies_b64` directly) but drop the now-irrelevant `FAMILYLINK_GOOGLE_EMAIL`/`PASSWORD`/`TOTP_SECRET` env var setup.

- [ ] **Step 1: Write the failing test for the missing-state-file error path**

Add to `tests/server/test_cookie_refresher.py`:

```python
def test_refresh_missing_state(monkeypatch, tmp_path):
    """POST /refresh returns 500 with a clear message when no state file exists."""
    monkeypatch.setenv('STATE_PATH', str(tmp_path / 'missing.json'))
    from familylink_server.cookie_refresher_app import app

    client = TestClient(app)
    resp = client.post('/refresh')
    assert resp.status_code == 500
    assert 'run bootstrap first' in resp.json()['detail']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_cookie_refresher.py::test_refresh_missing_state -v`
Expected: FAIL — current `/refresh` returns `400 Missing env vars: FAMILYLINK_GOOGLE_EMAIL, ...` instead of `500`.

- [ ] **Step 3: Write the failing test for expired-session detection**

Add to `tests/server/test_cookie_refresher.py`:

```python
def test_get_cookies_b64_raises_when_expired(monkeypatch, tmp_path):
    """_get_cookies_b64 raises RuntimeError when navigation produces no SAPISID cookie."""
    import sys
    import types

    state_path = tmp_path / 'state.json'
    state_path.write_text('{"cookies": [], "origins": []}')

    consent_only = [
        {
            'domain': '.google.com',
            'path': '/',
            'name': 'NID',
            'value': 'x',
            'secure': True,
            'expires': 9999999999,
        },
    ]

    class FakePage:
        url = 'https://myaccount.google.com/'

        def goto(self, *a, **kw):
            pass

        def title(self):
            return 'My Account'

    class FakeContext:
        def new_page(self):
            return FakePage()

        def cookies(self):
            return consent_only

        def storage_state(self, path=None):
            return {'cookies': consent_only, 'origins': []}

    class FakeBrowser:
        def new_context(self, **kw):
            return FakeContext()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **kw):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    fake_sync_api = types.ModuleType('playwright.sync_api')
    fake_sync_api.sync_playwright = lambda: FakePlaywright()

    fake_playwright_pkg = types.ModuleType('playwright')
    fake_playwright_pkg.sync_api = fake_sync_api

    monkeypatch.setitem(sys.modules, 'playwright', fake_playwright_pkg)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', fake_sync_api)

    import pytest

    from familylink_server.cookie_refresher_app import _get_cookies_b64

    with pytest.raises(RuntimeError, match='expired'):
        _get_cookies_b64(state_path)
```

- [ ] **Step 4: Write the failing test for navigation-failure diagnostics**

Add to `tests/server/test_cookie_refresher.py`:

```python
def test_get_cookies_b64_includes_page_context_on_failure(monkeypatch, tmp_path):
    """_get_cookies_b64 error message includes page URL/title when navigation fails."""
    import sys
    import types

    state_path = tmp_path / 'state.json'
    state_path.write_text('{"cookies": [], "origins": []}')

    class FakePage:
        url = 'https://accounts.google.com/v3/signin/challenge/az'

        def goto(self, *a, **kw):
            raise TimeoutError('Timeout 30000ms exceeded waiting for navigation')

        def title(self):
            return "Couldn't sign you in"

    class FakeContext:
        def new_page(self):
            return FakePage()

        def cookies(self):
            return []

        def storage_state(self, path=None):
            return {'cookies': [], 'origins': []}

    class FakeBrowser:
        def new_context(self, **kw):
            return FakeContext()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **kw):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    fake_sync_api = types.ModuleType('playwright.sync_api')
    fake_sync_api.sync_playwright = lambda: FakePlaywright()

    fake_playwright_pkg = types.ModuleType('playwright')
    fake_playwright_pkg.sync_api = fake_sync_api

    monkeypatch.setitem(sys.modules, 'playwright', fake_playwright_pkg)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', fake_sync_api)

    import pytest

    from familylink_server.cookie_refresher_app import _get_cookies_b64

    with pytest.raises(RuntimeError) as exc_info:
        _get_cookies_b64(state_path)

    message = str(exc_info.value)
    assert 'accounts.google.com/v3/signin/challenge/az' in message
    assert "Couldn't sign you in" in message
```

- [ ] **Step 5: Write the failing test for successful refresh + state rotation**

Add to `tests/server/test_cookie_refresher.py`:

```python
def test_get_cookies_b64_writes_rotated_state(monkeypatch, tmp_path):
    """_get_cookies_b64 loads from and persists back to the same state file."""
    import sys
    import types

    state_path = tmp_path / 'state.json'
    state_path.write_text('{"cookies": [], "origins": []}')

    fresh_cookies = [
        {
            'domain': '.google.com',
            'path': '/',
            'name': 'SAPISID',
            'value': 'y',
            'secure': True,
            'expires': 9999999999,
        },
    ]

    written = {}

    class FakePage:
        url = 'https://myaccount.google.com/'

        def goto(self, *a, **kw):
            pass

    class FakeContext:
        def new_page(self):
            return FakePage()

        def cookies(self):
            return fresh_cookies

        def storage_state(self, path=None):
            written['path'] = path
            return {'cookies': fresh_cookies, 'origins': []}

    class FakeBrowser:
        def new_context(self, **kw):
            written['loaded_from'] = kw.get('storage_state')
            return FakeContext()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **kw):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    fake_sync_api = types.ModuleType('playwright.sync_api')
    fake_sync_api.sync_playwright = lambda: FakePlaywright()

    fake_playwright_pkg = types.ModuleType('playwright')
    fake_playwright_pkg.sync_api = fake_sync_api

    monkeypatch.setitem(sys.modules, 'playwright', fake_playwright_pkg)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', fake_sync_api)

    from familylink_server.cookie_refresher_app import _get_cookies_b64

    result = _get_cookies_b64(state_path)

    assert written['loaded_from'] == str(state_path)
    assert written['path'] == str(state_path)

    import base64

    assert base64.b64decode(result).decode().count('SAPISID') == 1
```

- [ ] **Step 6: Run all four new tests to verify they fail**

Run: `python -m pytest tests/server/test_cookie_refresher.py::test_refresh_missing_state tests/server/test_cookie_refresher.py::test_get_cookies_b64_raises_when_expired tests/server/test_cookie_refresher.py::test_get_cookies_b64_includes_page_context_on_failure tests/server/test_cookie_refresher.py::test_get_cookies_b64_writes_rotated_state -v`
Expected: all 4 FAIL — `_get_cookies_b64` still takes `(email, password, totp_secret)`, so these calls raise `TypeError`.

- [ ] **Step 7: Delete the obsolete login-flow tests**

In `tests/server/test_cookie_refresher.py`, delete these four test functions entirely (they test behavior that no longer exists): `test_refresh_missing_password`, `test_refresh_missing_totp`, `test_get_cookies_b64_raises_when_no_sapisid` (the old email/password/TOTP-login version — not to be confused with the new `test_get_cookies_b64_raises_when_expired` added in Step 3), and the old `test_get_cookies_b64_includes_page_context_on_failure` (replaced by the new version added in Step 4 — delete the old one, keep the new one).

- [ ] **Step 8: Update `test_refresh_success`, `test_refresh_playwright_error`, `test_refresh_forbidden_when_wrong_key`, `test_refresh_allowed_when_key_matches`**

Remove the `monkeypatch.setenv('FAMILYLINK_GOOGLE_EMAIL', ...)`, `monkeypatch.setenv('FAMILYLINK_GOOGLE_PASSWORD', ...)`, and `monkeypatch.setenv('FAMILYLINK_TOTP_SECRET', ...)` lines from each of these four tests — they're no longer required by `/refresh`. Leave everything else in those tests unchanged (the `patch('familylink_server.cookie_refresher_app._get_cookies_b64', ...)` mocking still works identically since it patches the whole function regardless of its new signature).

- [ ] **Step 9: Rewrite `_get_cookies_b64` and `/refresh`**

In `src/familylink_server/cookie_refresher_app.py`, replace the entire block from `def _get_cookies_b64(email: str, password: str, totp_secret: str) -> str:` through the end of the `refresh()` function (everything from the current line 34 to the end of the file) with:

```python
def _get_cookies_b64(state_path: Path) -> str:
    """Replay a persisted Google session; return base64-encoded cookies.txt."""
    if not state_path.exists():
        raise RuntimeError(
            f'No persisted session at {state_path} — run bootstrap first'
        )

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(state_path))
        page = ctx.new_page()

        try:
            page.goto('https://myaccount.google.com/', wait_until='networkidle')
        except Exception as exc:
            try:
                title = page.title()
            except Exception:
                title = '<unavailable>'
            browser.close()
            raise RuntimeError(
                f'Refresh navigation failed at {page.url!r} (title={title!r}): {exc}'
            ) from exc

        google_cookies = [c for c in ctx.cookies() if 'google.com' in c['domain']]
        if not any(c['name'] == 'SAPISID' for c in google_cookies):
            browser.close()
            raise RuntimeError(
                'Persisted session has no SAPISID after navigation — it has '
                'expired. Re-run scripts/bootstrap_refresher_session.py.'
            )

        ctx.storage_state(path=str(state_path))
        browser.close()

    logger.info('Refresh: extracted %d google.com cookies', len(google_cookies))
    return base64.b64encode(_to_netscape(google_cookies).encode()).decode()


@app.post('/refresh')
async def refresh(x_api_key: str = Header(default='')) -> dict:
    """Replay the persisted Google session; return fresh base64 cookies."""
    expected = os.environ.get('REFRESHER_API_KEY', '')
    if expected and x_api_key != expected:
        raise HTTPException(403, 'Forbidden')

    state_path = Path(os.environ.get('STATE_PATH', '/data/state.json'))

    try:
        cookies_b64 = await asyncio.to_thread(_get_cookies_b64, state_path)
        return {'cookies_b64': cookies_b64}
    except Exception as exc:
        logger.error('Refresh failed: %s', exc)
        raise HTTPException(500, str(exc))
```

- [ ] **Step 10: Remove `pyotp` from the `[refresher]` extra**

In `pyproject.toml`, find the `refresher = [` block and remove the `"pyotp>=2.9",` line, so it reads:

```toml
refresher = [
    "playwright>=1.40",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
]
```

- [ ] **Step 11: Run the full cookie-refresher test file to verify everything passes**

Run: `python -m pytest tests/server/test_cookie_refresher.py -v`
Expected: all tests pass (should be around 12: `test_to_netscape_*` x3, `test_health_endpoint`, `test_bootstrap_writes_state_file`, `test_bootstrap_forbidden_when_wrong_key`, `test_refresh_missing_state`, `test_refresh_success`, `test_refresh_playwright_error`, `test_get_cookies_b64_raises_when_expired`, `test_get_cookies_b64_includes_page_context_on_failure`, `test_get_cookies_b64_writes_rotated_state`, `test_refresh_forbidden_when_wrong_key`, `test_refresh_allowed_when_key_matches`).

- [ ] **Step 12: Lint and format**

Run: `ruff check --fix src/familylink_server/cookie_refresher_app.py tests/server/test_cookie_refresher.py && ruff format src/familylink_server/cookie_refresher_app.py tests/server/test_cookie_refresher.py`
Expected: no errors.

- [ ] **Step 13: Reinstall the `[refresher]` extra to drop `pyotp` from the venv**

Run: `pip install -e ".[refresher]" -q`
Expected: completes without error (uninstalling `pyotp` isn't required for tests to pass, but keeps the local venv matching `pyproject.toml`).

- [ ] **Step 14: Commit**

```bash
git add src/familylink_server/cookie_refresher_app.py tests/server/test_cookie_refresher.py pyproject.toml
git commit -m "feat: replace password+TOTP login with persisted-session replay in /refresh"
```

---

### Task 3: Main app — `POST /admin/refresher-bootstrap` proxy endpoint

**Files:**
- Modify: `src/familylink_server/routers/admin.py`
- Create: `tests/server/test_routers_admin.py`

**Interfaces:**
- Consumes: `settings.cookie_refresher_url`, `settings.refresher_api_key` (both already exist on `Settings` in `src/familylink_server/config.py:24-25`).
- Produces: `POST /admin/refresher-bootstrap` on the main app — forwards the raw request body to `{settings.cookie_refresher_url}/bootstrap` with header `X-Api-Key: {settings.refresher_api_key}`. Requires the caller to send a matching `X-Api-Key` header itself (checked against `settings.refresher_api_key`). Returns `204` on success, `403` on bad key, `400` if `COOKIE_REFRESHER_URL` isn't configured.

- [ ] **Step 1: Write the failing test for a successful proxy**

Create `tests/server/test_routers_admin.py`:

```python
"""Tests for the /admin router's refresher-bootstrap proxy endpoint."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from familylink_server.config import settings
from familylink_server.routers.admin import router as admin_router


@pytest.fixture
def client():
    """Provide a TestClient with only the admin router mounted (no lifespan)."""
    app = FastAPI()
    app.include_router(admin_router)
    return TestClient(app)


def test_refresher_bootstrap_proxies_to_sidecar(client, httpx_mock, monkeypatch):
    """POST /admin/refresher-bootstrap forwards the body to the sidecar's /bootstrap."""
    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://cookie-refresher:8080')
    monkeypatch.setattr(settings, 'refresher_api_key', 'secret')

    httpx_mock.add_response(
        url='http://cookie-refresher:8080/bootstrap',
        method='POST',
        status_code=204,
    )

    resp = client.post(
        '/admin/refresher-bootstrap',
        json={'cookies': [{'name': 'SAPISID', 'value': 'abc'}], 'origins': []},
        headers={'X-Api-Key': 'secret'},
    )
    assert resp.status_code == 204

    request = httpx_mock.get_requests()[-1]
    assert request.headers['X-Api-Key'] == 'secret'
    assert b'SAPISID' in request.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_routers_admin.py::test_refresher_bootstrap_proxies_to_sidecar -v`
Expected: FAIL with `404 Not Found` — route doesn't exist yet.

- [ ] **Step 3: Write the failing test for the wrong-API-key case**

Add to `tests/server/test_routers_admin.py`:

```python
def test_refresher_bootstrap_forbidden_when_wrong_key(client, monkeypatch):
    """POST /admin/refresher-bootstrap returns 403 when X-Api-Key doesn't match."""
    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://cookie-refresher:8080')
    monkeypatch.setattr(settings, 'refresher_api_key', 'secret')

    resp = client.post(
        '/admin/refresher-bootstrap',
        json={'cookies': [], 'origins': []},
        headers={'X-Api-Key': 'wrong'},
    )
    assert resp.status_code == 403
```

- [ ] **Step 4: Write the failing test for missing sidecar configuration**

Add to `tests/server/test_routers_admin.py`:

```python
def test_refresher_bootstrap_fails_when_sidecar_not_configured(client, monkeypatch):
    """POST /admin/refresher-bootstrap returns 400 when COOKIE_REFRESHER_URL is unset."""
    monkeypatch.setattr(settings, 'cookie_refresher_url', '')
    monkeypatch.setattr(settings, 'refresher_api_key', 'secret')

    resp = client.post(
        '/admin/refresher-bootstrap',
        json={'cookies': [], 'origins': []},
        headers={'X-Api-Key': 'secret'},
    )
    assert resp.status_code == 400
```

- [ ] **Step 5: Run the new tests to verify they fail**

Run: `python -m pytest tests/server/test_routers_admin.py -v`
Expected: all 3 FAIL with `404 Not Found`.

- [ ] **Step 6: Implement `POST /admin/refresher-bootstrap`**

In `src/familylink_server/routers/admin.py`, update the imports at the top from:

```python
import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import get_service
```

to:

```python
import logging

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from familylink_server.auth.oauth import require_user
from familylink_server.config import settings
from familylink_server.services.family_link import get_service
```

Add this endpoint at the end of the file, after `refresh_cookies()`:

```python
@router.post('/refresher-bootstrap', status_code=204)
async def refresher_bootstrap(
    request: Request, x_api_key: str = Header(default='')
) -> None:
    """Proxy a bootstrapped Playwright storage_state to the cookie-refresher sidecar."""
    expected = settings.refresher_api_key
    if expected and x_api_key != expected:
        raise HTTPException(403, 'Forbidden')
    if not settings.cookie_refresher_url:
        raise HTTPException(400, 'COOKIE_REFRESHER_URL is not configured')

    body = await request.body()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f'{settings.cookie_refresher_url}/bootstrap',
            content=body,
            headers={
                'Content-Type': 'application/json',
                'X-Api-Key': settings.refresher_api_key,
            },
            timeout=30,
        )
        resp.raise_for_status()
    logger.info('Bootstrap proxied to cookie-refresher sidecar')
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_routers_admin.py -v`
Expected: `3 passed`

- [ ] **Step 8: Run the full test suite to check for regressions**

Run: `python -m pytest`
Expected: all tests pass, no regressions in `admin.py`'s existing endpoints.

- [ ] **Step 9: Lint and format**

Run: `ruff check --fix src/familylink_server/routers/admin.py tests/server/test_routers_admin.py && ruff format src/familylink_server/routers/admin.py tests/server/test_routers_admin.py`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add src/familylink_server/routers/admin.py tests/server/test_routers_admin.py
git commit -m "feat: add POST /admin/refresher-bootstrap proxy endpoint"
```

---

### Task 4: Deployment config — volume, env var cleanup

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: nothing new from earlier tasks.
- Produces: `cookie-refresher` service in `docker-compose.yml` has a named volume mounted at `/data` (matches the `STATE_PATH` default from Task 1/2) and no longer sets `FAMILYLINK_GOOGLE_EMAIL`, `FAMILYLINK_GOOGLE_PASSWORD`, or `FAMILYLINK_TOTP_SECRET`.

- [ ] **Step 1: Update `docker-compose.yml`**

Replace the `cookie-refresher` service block:

```yaml
  cookie-refresher:
    build:
      context: .
      dockerfile: Dockerfile.refresher
    restart: unless-stopped
    environment:
      FAMILYLINK_GOOGLE_EMAIL: ${FAMILYLINK_GOOGLE_EMAIL:-}
      FAMILYLINK_GOOGLE_PASSWORD: ${FAMILYLINK_GOOGLE_PASSWORD:-}
      FAMILYLINK_TOTP_SECRET: ${FAMILYLINK_TOTP_SECRET:-}
      REFRESHER_API_KEY: ${REFRESHER_API_KEY:-}
```

with:

```yaml
  cookie-refresher:
    build:
      context: .
      dockerfile: Dockerfile.refresher
    restart: unless-stopped
    environment:
      REFRESHER_API_KEY: ${REFRESHER_API_KEY:-}
    volumes:
      - refresher_state:/data
```

Add `refresher_state:` to the `volumes:` block at the bottom of the file, so it reads:

```yaml
volumes:
  pgdata:
  refresher_state:
```

- [ ] **Step 2: Validate compose syntax**

Run: `docker compose config --services`
Expected: prints `db`, `cookie-refresher`, `web` with no parse errors.

- [ ] **Step 3: Update `.env.example`**

Replace the block from `# ------------------------------------------\n# Cookie-refresher sidecar (optional...` through the end of the `FAMILYLINK_TOTP_SECRET` section (lines 85-109) with:

```
# ------------------------------------------
# Cookie-refresher sidecar (optional — enables automatic session recovery)
# Set on the MAIN SERVER. See README.md "Auto-refresh sidecar" section for
# the full bootstrap flow — the sidecar itself needs no Google credentials.
# ------------------------------------------

# Internal URL of the cookie-refresher service
# Docker Compose: http://cookie-refresher:8080
# Coolify: use the internal service URL (same project network)
# COOKIE_REFRESHER_URL=http://cookie-refresher:8080

# Shared secret — must match REFRESHER_API_KEY on the sidecar
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
# REFRESHER_API_KEY=<random 32-byte hex>
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "chore: mount persisted-session volume, drop sidecar credential env vars"
```

---

### Task 5: Bootstrap script

**Files:**
- Create: `scripts/bootstrap_refresher_session.py`
- Create: `tests/scripts/test_bootstrap_refresher_session.py`
- Delete: `scripts/debug_refresher.py`

**Interfaces:**
- Produces: `_cookiejar_to_storage_state(cookies: list) -> dict` — pure function, takes an iterable of cookie-like objects (each with `.domain`, `.name`, `.value`, `.path`, `.expires`, `.secure` attributes — matches `http.cookiejar.Cookie`, which is what `browser_cookie3` returns), filters to `google.com` domains, returns a Playwright `storage_state` dict `{"cookies": [...], "origins": []}`.
- `main() -> int` — CLI entry point; reads `WEB_BASE_URL` and `REFRESHER_API_KEY` from the environment, extracts cookies via `browser_cookie3`, POSTs to `{WEB_BASE_URL}/admin/refresher-bootstrap`.

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_bootstrap_refresher_session.py`:

```python
"""Tests for the cookie-refresher bootstrap script's pure conversion logic."""


class _FakeCookie:
    def __init__(self, domain, name, value, path='/', expires=123, secure=True):
        self.domain = domain
        self.name = name
        self.value = value
        self.path = path
        self.expires = expires
        self.secure = secure


def test_cookiejar_to_storage_state_filters_and_converts():
    """Only google.com cookies are kept; fields map to Playwright's schema."""
    from scripts.bootstrap_refresher_session import _cookiejar_to_storage_state

    cookies = [
        _FakeCookie('.google.com', 'SAPISID', 'abc'),
        _FakeCookie('.example.com', 'OTHER', 'xyz'),
    ]
    result = _cookiejar_to_storage_state(cookies)

    assert result['origins'] == []
    assert len(result['cookies']) == 1
    c = result['cookies'][0]
    assert c['name'] == 'SAPISID'
    assert c['domain'] == '.google.com'
    assert c['secure'] is True
    assert c['sameSite'] == 'None'


def test_cookiejar_to_storage_state_handles_missing_expires():
    """A session cookie (expires=None/0) maps to Playwright's -1 sentinel."""
    from scripts.bootstrap_refresher_session import _cookiejar_to_storage_state

    cookies = [_FakeCookie('.google.com', 'SID', 'v', expires=0)]
    result = _cookiejar_to_storage_state(cookies)

    assert result['cookies'][0]['expires'] == -1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/scripts/test_bootstrap_refresher_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.bootstrap_refresher_session'`.

- [ ] **Step 3: Delete the old diagnostic script**

```bash
rm scripts/debug_refresher.py
```

- [ ] **Step 4: Write `scripts/bootstrap_refresher_session.py`**

```python
"""One-time (or rare re-auth) bootstrap for the cookie-refresher sidecar.

Captures a real, already-authenticated Google session from the operator's
own browser via browser_cookie3 (same mechanism `familylink export-cookies`
uses) and uploads it to the deployed sidecar through the main app's
X-Api-Key-protected admin proxy. No automated login ever runs, so there is
nothing for Google's anti-automation detection to block.

Usage:
    WEB_BASE_URL=https://your-app.example.com \
    REFRESHER_API_KEY=<shared secret> \
    python scripts/bootstrap_refresher_session.py [--browser chrome]
"""

import argparse
import json
import os
import sys


def _cookiejar_to_storage_state(cookies: list) -> dict:
    """Convert browser_cookie3 cookie objects to a Playwright storage_state dict."""
    playwright_cookies = []
    for c in cookies:
        if 'google.com' not in c.domain:
            continue
        playwright_cookies.append(
            {
                'name': c.name,
                'value': c.value,
                'domain': c.domain,
                'path': c.path,
                'expires': c.expires if c.expires else -1,
                'httpOnly': False,
                'secure': bool(c.secure),
                'sameSite': 'None',
            }
        )
    return {'cookies': playwright_cookies, 'origins': []}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--browser',
        default='chrome',
        help='browser_cookie3 function name to use (default: chrome)',
    )
    args = parser.parse_args()

    try:
        import browser_cookie3
    except ImportError:
        print(
            'browser_cookie3 not installed. Run: pip install browser_cookie3',
            file=sys.stderr,
        )
        return 1

    web_base_url = os.environ.get('WEB_BASE_URL', '').rstrip('/')
    api_key = os.environ.get('REFRESHER_API_KEY', '')
    if not web_base_url or not api_key:
        print('Set WEB_BASE_URL and REFRESHER_API_KEY env vars first.', file=sys.stderr)
        return 1

    jar = getattr(browser_cookie3, args.browser)(domain_name='google.com')
    storage_state = _cookiejar_to_storage_state(list(jar))

    if not any(c['name'] == 'SAPISID' for c in storage_state['cookies']):
        print(
            'No SAPISID cookie found — log into Google in that browser first.',
            file=sys.stderr,
        )
        return 1

    import httpx

    resp = httpx.post(
        f'{web_base_url}/admin/refresher-bootstrap',
        content=json.dumps(storage_state),
        headers={'Content-Type': 'application/json', 'X-Api-Key': api_key},
        timeout=30,
    )
    resp.raise_for_status()
    print(f'Bootstrapped {len(storage_state["cookies"])} cookies to the sidecar.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/scripts/test_bootstrap_refresher_session.py -v`
Expected: `2 passed`

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest`
Expected: all tests pass.

- [ ] **Step 7: Lint and format**

Run: `ruff check --fix scripts/bootstrap_refresher_session.py tests/scripts/test_bootstrap_refresher_session.py && ruff format scripts/bootstrap_refresher_session.py tests/scripts/test_bootstrap_refresher_session.py`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add scripts/bootstrap_refresher_session.py tests/scripts/test_bootstrap_refresher_session.py
git rm scripts/debug_refresher.py
git commit -m "feat: add bootstrap script for persisted-session cookie refresher"
```

---

### Task 6: Update knowledge graph and run manual verification

**Files:** none (tooling + manual steps only)

- [ ] **Step 1: Update graphify**

Run: `graphify update .`
Expected: completes, reports updated node/edge counts.

- [ ] **Step 2: Full suite + lint sanity check**

Run: `python -m pytest && ruff check src tests && mypy src`
Expected: all green. (The pre-existing `pyotp`/`playwright` mypy import-not-found warnings should now show only `playwright` — `pyotp` is gone.)

- [ ] **Step 3: Commit graphify update**

```bash
git add graphify-out
git commit -m "chore: update graphify knowledge graph"
```

- [ ] **Step 4: Manual end-to-end verification (cannot be automated — needs real credentials/deployment)**

1. Redeploy both `web` and `cookie-refresher` services (picks up the new volume mount and code).
2. From your laptop, logged into the parent Google account in real Chrome: `WEB_BASE_URL=https://<your-domain> REFRESHER_API_KEY=<key> python scripts/bootstrap_refresher_session.py`
3. Confirm it prints `Bootstrapped N cookies to the sidecar.`
4. `curl -X POST -H "X-Api-Key: <key>" http://<sidecar-internal>:8080/refresh` → expect `{"cookies_b64": "..."}` within ~30s.
5. On the main app, clear `FAMILYLINK_COOKIES_B64` and restart; wait for the next health check (or trigger manually) → confirm auto-refresh fires and a "✅ restored" Discord notification appears.
6. Confirm Family Link data loads in the UI without any manual reconnect.
