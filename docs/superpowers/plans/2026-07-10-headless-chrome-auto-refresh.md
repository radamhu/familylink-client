# Headless Chrome Auto-Cookie-Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `health_check_loop` detects a Google session expiry, automatically call a Playwright sidecar service to log into Google and refresh the full cookie jar — no human action required.

**Architecture:** A separate Docker service (`Dockerfile.refresher`) runs Playwright + Chromium and exposes `POST /refresh`. The main server calls it via `httpx.AsyncClient` when `SessionExpiredError` is detected, then hot-reloads `FamilyLinkService` with the fresh cookies using a new `reinit_with_cookies_b64()` method that replaces the full `FAMILYLINK_COOKIES_B64` env var in memory.

**Tech Stack:** Playwright (sync API via asyncio.to_thread), pyotp (TOTP generation), httpx.AsyncClient (existing dep), FastAPI (sidecar), pytest-httpx (mock async HTTP in tests)

## Global Constraints

- Python 3.12+; `asyncio_mode = "auto"` in pytest — all `async def test_*` are awaited automatically
- No `uv` — use `pip` and `python -m pytest`
- Ruff with Google docstring style, single-quoted strings — run `ruff check --fix` and `ruff format` before each commit
- Do not modify CLI (`cli.py`) or `/admin/reconnect` — out of scope
- `httpx` is already in base deps — no new dep needed in main image
- Tests use `_make_service()` pattern (bypass `__init__`) — follow `tests/server/test_cookie_hotreload.py`
- graphify-out/graph.json exists — run `graphify query "<question>"` before exploring source files

---

### Task 1: Refresher dep group + config field

**Files:**
- Modify: `pyproject.toml` (add `[refresher]` optional dep group)
- Modify: `src/familylink_server/config.py` (add `cookie_refresher_url` field)
- Test: `tests/server/test_auto_refresh.py` (new file, config field test only)

**Interfaces:**
- Produces: `settings.cookie_refresher_url: str` (default `""`)

- [ ] **Step 1: Write failing test**

Create `tests/server/test_auto_refresh.py`:
```python
"""Tests for auto-refresh via sidecar."""
import os
from unittest.mock import MagicMock, patch

import pytest

from familylink_server.services.family_link import FamilyLinkService


def _make_service():
    """Create FamilyLinkService bypassing __init__."""
    svc = FamilyLinkService.__new__(FamilyLinkService)
    svc._ttl = 0
    svc._members_cache = None
    svc._usage_cache = {}
    svc._auth_failed = False
    svc._client = MagicMock()
    return svc


def test_cookie_refresher_url_default():
    """cookie_refresher_url should default to empty string."""
    from familylink_server.config import settings
    assert settings.cookie_refresher_url == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/ferko/development/familylink-client
python -m pytest tests/server/test_auto_refresh.py::test_cookie_refresher_url_default -v
```
Expected: `AttributeError: 'Settings' object has no attribute 'cookie_refresher_url'`

- [ ] **Step 3: Add `cookie_refresher_url` to Settings**

In `src/familylink_server/config.py`, add after `familylink_sapisid`:
```python
cookie_refresher_url: str = ""
```

- [ ] **Step 4: Add `[refresher]` dep group to pyproject.toml**

In `pyproject.toml`, add after `[project.optional-dependencies]` entries (e.g. after `test`):
```toml
refresher = [
    "playwright>=1.40",
    "pyotp>=2.9",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
]
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest tests/server/test_auto_refresh.py::test_cookie_refresher_url_default -v
```
Expected: `PASSED`

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix src tests && ruff format src tests
git add pyproject.toml src/familylink_server/config.py tests/server/test_auto_refresh.py
git commit -m "feat: add [refresher] dep group and cookie_refresher_url config field"
```

---

### Task 2: `reinit_with_cookies_b64()` on FamilyLinkService

**Files:**
- Modify: `src/familylink_server/services/family_link.py` (new method after `reinit_with_cookies`)
- Test: `tests/server/test_auto_refresh.py` (append tests)

**Interfaces:**
- Consumes: existing `FamilyLinkService.__new__` + `_make_service()` from Task 1 test file
- Produces: `FamilyLinkService.reinit_with_cookies_b64(cookies_b64: str) -> None`

- [ ] **Step 1: Write failing tests**

Append to `tests/server/test_auto_refresh.py`:
```python
def test_reinit_with_cookies_b64_sets_env():
    """reinit_with_cookies_b64 should set FAMILYLINK_COOKIES_B64 in os.environ."""
    svc = _make_service()
    with patch("familylink_server.services.family_link.FamilyLink"):
        with patch.dict(os.environ, {}, clear=False):
            svc.reinit_with_cookies_b64("new_b64_value")
            assert os.environ.get("FAMILYLINK_COOKIES_B64") == "new_b64_value"


def test_reinit_with_cookies_b64_pops_sapisid():
    """reinit_with_cookies_b64 should remove FAMILYLINK_SAPISID from os.environ."""
    svc = _make_service()
    with patch("familylink_server.services.family_link.FamilyLink"):
        with patch.dict(os.environ, {"FAMILYLINK_SAPISID": "old_sid"}, clear=False):
            svc.reinit_with_cookies_b64("new_b64_value")
            assert "FAMILYLINK_SAPISID" not in os.environ


def test_reinit_with_cookies_b64_clears_caches():
    """reinit_with_cookies_b64 should clear caches and reset auth_failed."""
    svc = _make_service()
    svc._members_cache = (MagicMock(), MagicMock())
    svc._usage_cache = {"child1": (MagicMock(), MagicMock())}
    svc._auth_failed = True

    with patch("familylink_server.services.family_link.FamilyLink"):
        svc.reinit_with_cookies_b64("abc")

    assert svc._members_cache is None
    assert svc._usage_cache == {}
    assert svc._auth_failed is False


def test_reinit_with_cookies_b64_creates_new_client():
    """reinit_with_cookies_b64 should replace _client with new FamilyLink instance."""
    svc = _make_service()
    old_client = svc._client

    with patch("familylink_server.services.family_link.FamilyLink") as MockFL:
        MockFL.return_value = MagicMock()
        svc.reinit_with_cookies_b64("abc")

    assert svc._client is not old_client
    MockFL.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/server/test_auto_refresh.py -k "reinit_with_cookies_b64" -v
```
Expected: `AttributeError: 'FamilyLinkService' object has no attribute 'reinit_with_cookies_b64'`

- [ ] **Step 3: Add method to FamilyLinkService**

In `src/familylink_server/services/family_link.py`, add after `reinit_with_cookies` method (after line 41):
```python
def reinit_with_cookies_b64(self, cookies_b64: str) -> None:
    """Hot-swap the FamilyLink client with a full fresh cookie jar."""
    os.environ['FAMILYLINK_COOKIES_B64'] = cookies_b64
    os.environ.pop('FAMILYLINK_SAPISID', None)
    self._client = FamilyLink()
    self._members_cache = None
    self._usage_cache.clear()
    self._auth_failed = False
    logger.info('FamilyLink client reinitialized with fresh cookie jar')
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/server/test_auto_refresh.py -k "reinit_with_cookies_b64" -v
```
Expected: 4 tests `PASSED`

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
python -m pytest tests/server/test_cookie_hotreload.py tests/server/test_auto_refresh.py -v
```
Expected: all `PASSED`

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix src tests && ruff format src tests
git add src/familylink_server/services/family_link.py tests/server/test_auto_refresh.py
git commit -m "feat: add reinit_with_cookies_b64 to FamilyLinkService"
```

---

### Task 3: Sidecar app scaffold — `_to_netscape` + `/health`

**Files:**
- Create: `src/familylink_server/cookie_refresher_app.py`
- Create: `tests/server/test_cookie_refresher.py`

**Interfaces:**
- Produces:
  - `_to_netscape(cookies: list[dict]) -> str` — module-level, importable for tests
  - `GET /health` → `{"status": "ok"}`
  - `app: FastAPI` — the sidecar application object

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_cookie_refresher.py`:
```python
"""Tests for the cookie-refresher sidecar app."""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def test_to_netscape_subdomain_flag():
    """Domains starting with '.' should use TRUE for include_subdomains."""
    from familylink_server.cookie_refresher_app import _to_netscape
    cookies = [{"name": "SAPISID", "value": "abc/def", "domain": ".google.com",
                "path": "/", "expires": 1234567890.0, "secure": True}]
    result = _to_netscape(cookies)
    assert result.startswith("# Netscape HTTP Cookie File\n")
    assert ".google.com\tTRUE\t/\tTRUE\t1234567890\tSAPISID\tabc/def" in result


def test_to_netscape_non_subdomain():
    """Domains not starting with '.' should use FALSE for include_subdomains."""
    from familylink_server.cookie_refresher_app import _to_netscape
    cookies = [{"name": "SESSION", "value": "xyz", "domain": "accounts.google.com",
                "path": "/", "expires": 0, "secure": False}]
    result = _to_netscape(cookies)
    assert "accounts.google.com\tFALSE\t/\tFALSE\t0\tSESSION\txyz" in result


def test_to_netscape_missing_expires():
    """Cookies without 'expires' key should default to expiry 0."""
    from familylink_server.cookie_refresher_app import _to_netscape
    cookies = [{"name": "X", "value": "y", "domain": ".g.com", "path": "/", "secure": False}]
    result = _to_netscape(cookies)
    assert "\t0\tX\ty" in result


def test_health_endpoint():
    """GET /health should return 200 with status ok."""
    from familylink_server.cookie_refresher_app import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/server/test_cookie_refresher.py -v
```
Expected: `ModuleNotFoundError: No module named 'familylink_server.cookie_refresher_app'`

- [ ] **Step 3: Create the sidecar app scaffold**

Create `src/familylink_server/cookie_refresher_app.py`:
```python
"""Sidecar: headless Chrome cookie refresher service."""

import base64
import logging
import os

from fastapi import FastAPI, HTTPException

logger = logging.getLogger(__name__)

app = FastAPI(title='cookie-refresher')


def _to_netscape(cookies: list[dict]) -> str:
    """Convert Playwright cookie dicts to Netscape cookies.txt format."""
    lines = ['# Netscape HTTP Cookie File']
    for c in cookies:
        sub = 'TRUE' if c['domain'].startswith('.') else 'FALSE'
        secure = 'TRUE' if c.get('secure') else 'FALSE'
        exp = int(c.get('expires') or 0)
        lines.append(
            f'{c["domain"]}\t{sub}\t{c["path"]}\t{secure}\t{exp}\t{c["name"]}\t{c["value"]}'
        )
    return '\n'.join(lines) + '\n'


@app.get('/health')
async def health() -> dict:
    """Liveness probe."""
    return {'status': 'ok'}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/server/test_cookie_refresher.py -v
```
Expected: 4 tests `PASSED`

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix src tests && ruff format src tests
git add src/familylink_server/cookie_refresher_app.py tests/server/test_cookie_refresher.py
git commit -m "feat: add cookie_refresher_app scaffold with _to_netscape helper"
```

---

### Task 4: Sidecar `POST /refresh` endpoint + `Dockerfile.refresher`

**Files:**
- Modify: `src/familylink_server/cookie_refresher_app.py` (add `_get_cookies_b64` + `POST /refresh`)
- Create: `Dockerfile.refresher`
- Test: `tests/server/test_cookie_refresher.py` (append tests)

**Interfaces:**
- Consumes: `_to_netscape()` from Task 3
- Produces:
  - `_get_cookies_b64(email: str, password: str, totp_secret: str) -> str` — sync, runs Playwright
  - `POST /refresh` → `{"cookies_b64": str}` on success, 400 if env vars missing, 500 on Playwright failure

- [ ] **Step 1: Write failing tests**

Append to `tests/server/test_cookie_refresher.py`:
```python
def test_refresh_missing_password(monkeypatch):
    """POST /refresh should return 400 when FAMILYLINK_GOOGLE_PASSWORD is unset."""
    monkeypatch.delenv('FAMILYLINK_GOOGLE_PASSWORD', raising=False)
    monkeypatch.setenv('FAMILYLINK_GOOGLE_EMAIL', 'test@gmail.com')
    monkeypatch.setenv('FAMILYLINK_TOTP_SECRET', 'JBSWY3DPEHPK3PXP')
    from familylink_server.cookie_refresher_app import app
    client = TestClient(app)
    resp = client.post('/refresh')
    assert resp.status_code == 400
    assert 'FAMILYLINK_GOOGLE_PASSWORD' in resp.json()['detail']


def test_refresh_missing_totp(monkeypatch):
    """POST /refresh should return 400 when FAMILYLINK_TOTP_SECRET is unset."""
    monkeypatch.setenv('FAMILYLINK_GOOGLE_EMAIL', 'test@gmail.com')
    monkeypatch.setenv('FAMILYLINK_GOOGLE_PASSWORD', 'secret')
    monkeypatch.delenv('FAMILYLINK_TOTP_SECRET', raising=False)
    from familylink_server.cookie_refresher_app import app
    client = TestClient(app)
    resp = client.post('/refresh')
    assert resp.status_code == 400


def test_refresh_success(monkeypatch):
    """POST /refresh should return cookies_b64 when _get_cookies_b64 succeeds."""
    monkeypatch.setenv('FAMILYLINK_GOOGLE_EMAIL', 'test@gmail.com')
    monkeypatch.setenv('FAMILYLINK_GOOGLE_PASSWORD', 'secret')
    monkeypatch.setenv('FAMILYLINK_TOTP_SECRET', 'JBSWY3DPEHPK3PXP')

    with patch(
        'familylink_server.cookie_refresher_app._get_cookies_b64',
        return_value='dGVzdA=='
    ):
        from familylink_server.cookie_refresher_app import app
        client = TestClient(app)
        resp = client.post('/refresh')

    assert resp.status_code == 200
    assert resp.json() == {'cookies_b64': 'dGVzdA=='}


def test_refresh_playwright_error(monkeypatch):
    """POST /refresh should return 500 when Playwright login fails."""
    monkeypatch.setenv('FAMILYLINK_GOOGLE_EMAIL', 'test@gmail.com')
    monkeypatch.setenv('FAMILYLINK_GOOGLE_PASSWORD', 'secret')
    monkeypatch.setenv('FAMILYLINK_TOTP_SECRET', 'JBSWY3DPEHPK3PXP')

    with patch(
        'familylink_server.cookie_refresher_app._get_cookies_b64',
        side_effect=RuntimeError('CAPTCHA detected')
    ):
        from familylink_server.cookie_refresher_app import app
        client = TestClient(app)
        resp = client.post('/refresh')

    assert resp.status_code == 500
    assert 'CAPTCHA' in resp.json()['detail']
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/server/test_cookie_refresher.py -k "refresh" -v
```
Expected: `AttributeError` or import error — `/refresh` endpoint not yet defined

- [ ] **Step 3: Add `_get_cookies_b64` and `POST /refresh` to the sidecar app**

Append to `src/familylink_server/cookie_refresher_app.py` (after the `/health` endpoint):
```python
def _get_cookies_b64(email: str, password: str, totp_secret: str) -> str:
    """Log into Google via headless Chromium; return base64-encoded cookies.txt."""
    import asyncio

    import pyotp
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
        )
        page = ctx.new_page()

        page.goto(
            'https://accounts.google.com/signin/v2/identifier',
            wait_until='networkidle',
        )
        page.fill('input[type="email"]', email)
        page.click('#identifierNext')
        page.wait_for_load_state('networkidle')

        page.fill('input[type="password"]', password)
        page.click('#passwordNext')
        page.wait_for_load_state('networkidle')

        totp_el = page.query_selector('input[type="tel"], input[type="number"]')
        if totp_el:
            totp_el.fill(pyotp.TOTP(totp_secret).now())
            page.keyboard.press('Enter')
            page.wait_for_load_state('networkidle')

        google_cookies = [c for c in ctx.cookies() if 'google.com' in c['domain']]
        browser.close()

    logger.info('Auto-refresh: extracted %d google.com cookies', len(google_cookies))
    return base64.b64encode(_to_netscape(google_cookies).encode()).decode()


@app.post('/refresh')
async def refresh() -> dict:
    """Run headless Chrome login; return fresh base64 cookies."""
    import asyncio

    email = os.environ.get('FAMILYLINK_GOOGLE_EMAIL', '')
    password = os.environ.get('FAMILYLINK_GOOGLE_PASSWORD', '')
    totp_secret = os.environ.get('FAMILYLINK_TOTP_SECRET', '')

    missing = [
        v for v, k in [
            ('FAMILYLINK_GOOGLE_EMAIL', email),
            ('FAMILYLINK_GOOGLE_PASSWORD', password),
            ('FAMILYLINK_TOTP_SECRET', totp_secret),
        ]
        if not k
    ]
    if missing:
        raise HTTPException(400, f'Missing env vars: {", ".join(missing)}')

    try:
        cookies_b64 = await asyncio.to_thread(_get_cookies_b64, email, password, totp_secret)
        return {'cookies_b64': cookies_b64}
    except Exception as exc:
        logger.error('Playwright login failed: %s', exc)
        raise HTTPException(500, str(exc))
```

Note: The `missing` list comprehension above has a bug — swap the tuple order. Replace that block with:
```python
    missing = [name for name, val in [
        ('FAMILYLINK_GOOGLE_EMAIL', email),
        ('FAMILYLINK_GOOGLE_PASSWORD', password),
        ('FAMILYLINK_TOTP_SECRET', totp_secret),
    ] if not val]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/server/test_cookie_refresher.py -v
```
Expected: all 8 tests `PASSED`

- [ ] **Step 5: Create `Dockerfile.refresher`**

Create `Dockerfile.refresher` at repo root:
```dockerfile
# Sidecar image: Playwright + Chromium for headless cookie refresh
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[refresher]" \
    && playwright install --with-deps chromium \
    && apt-get purge -y gcc && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["uvicorn", "familylink_server.cookie_refresher_app:app", \
     "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix src tests && ruff format src tests
git add src/familylink_server/cookie_refresher_app.py tests/server/test_cookie_refresher.py Dockerfile.refresher
git commit -m "feat: add cookie-refresher sidecar app with Playwright login and Dockerfile"
```

---

### Task 5: `_try_auto_refresh()` in main.py

**Files:**
- Modify: `src/familylink_server/main.py` (add `import httpx`; add `_try_auto_refresh` function)
- Test: `tests/server/test_auto_refresh.py` (append tests)

**Interfaces:**
- Consumes: `settings.cookie_refresher_url: str` (Task 1), `service.reinit_with_cookies_b64()` (Task 2)
- Produces: `async def _try_auto_refresh(service: FamilyLinkService, notifier: DiscordNotifier | None) -> bool`

- [ ] **Step 1: Write failing tests**

Append to `tests/server/test_auto_refresh.py`:
```python
async def test_try_auto_refresh_no_op_when_url_not_set(monkeypatch):
    """_try_auto_refresh should return False immediately when COOKIE_REFRESHER_URL is empty."""
    from familylink_server.config import settings
    from familylink_server.main import _try_auto_refresh

    monkeypatch.setattr(settings, 'cookie_refresher_url', '')
    svc = _make_service()
    result = await _try_auto_refresh(svc, None)
    assert result is False
    assert svc._auth_failed is False  # untouched


async def test_try_auto_refresh_success(httpx_mock, monkeypatch):
    """_try_auto_refresh should call sidecar, reinit service, and return True on success."""
    from familylink_server.config import settings
    from familylink_server.main import _try_auto_refresh

    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://sidecar:8080')
    httpx_mock.add_response(
        url='http://sidecar:8080/refresh',
        method='POST',
        json={'cookies_b64': 'dGVzdA=='},
    )

    svc = _make_service()
    with patch('familylink_server.services.family_link.FamilyLink'):
        result = await _try_auto_refresh(svc, None)

    assert result is True
    assert os.environ.get('FAMILYLINK_COOKIES_B64') == 'dGVzdA=='
    assert svc._auth_failed is False


async def test_try_auto_refresh_returns_false_on_http_error(httpx_mock, monkeypatch):
    """_try_auto_refresh should return False when sidecar returns non-2xx."""
    from familylink_server.config import settings
    from familylink_server.main import _try_auto_refresh

    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://sidecar:8080')
    httpx_mock.add_response(
        url='http://sidecar:8080/refresh',
        method='POST',
        status_code=500,
        text='Playwright error',
    )

    svc = _make_service()
    result = await _try_auto_refresh(svc, None)
    assert result is False


async def test_try_auto_refresh_returns_false_on_network_error(monkeypatch):
    """_try_auto_refresh should return False on connection error without raising."""
    import httpx as _httpx
    from familylink_server.config import settings
    from familylink_server.main import _try_auto_refresh

    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://sidecar:8080')

    with patch('httpx.AsyncClient') as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = MagicMock(return_value=mock_client)
        mock_client.__aexit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(side_effect=_httpx.ConnectError('refused'))
        mock_client_cls.return_value = mock_client

        svc = _make_service()
        result = await _try_auto_refresh(svc, None)

    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/server/test_auto_refresh.py -k "try_auto_refresh" -v
```
Expected: `ImportError: cannot import name '_try_auto_refresh' from 'familylink_server.main'`

- [ ] **Step 3: Add `import httpx` and `_try_auto_refresh` to main.py**

In `src/familylink_server/main.py`, add `import httpx` to the existing imports block (near the top, after stdlib imports).

Then add this function after the `health_check_loop` function and before the `lifespan` context manager:
```python
async def _try_auto_refresh(
    service: 'FamilyLinkService',
    notifier: 'DiscordNotifier | None',
) -> bool:
    """Call cookie-refresher sidecar; hot-reload service. Returns True on success."""
    url = settings.cookie_refresher_url
    if not url:
        return False
    try:
        logger.info('Auto-refresh: calling sidecar at %s/refresh', url)
        async with httpx.AsyncClient() as client:
            resp = await client.post(f'{url}/refresh', timeout=120)
            resp.raise_for_status()
        cookies_b64 = resp.json()['cookies_b64']
        service.reinit_with_cookies_b64(cookies_b64)
        if notifier:
            await notifier.notify_session_restored()
        logger.info('Auto-refresh: success')
        return True
    except Exception as exc:
        logger.error('Auto-refresh: failed — %s', exc)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/server/test_auto_refresh.py -k "try_auto_refresh" -v
```
Expected: 4 tests `PASSED`

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```
Expected: all existing tests still `PASSED`

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix src tests && ruff format src tests
git add src/familylink_server/main.py tests/server/test_auto_refresh.py
git commit -m "feat: add _try_auto_refresh helper to call cookie-refresher sidecar"
```

---

### Task 6: Wire `_try_auto_refresh` into `health_check_loop`

**Files:**
- Modify: `src/familylink_server/main.py` (update `health_check_loop`)
- Test: `tests/server/test_auto_refresh.py` (append integration test)

**Interfaces:**
- Consumes: `_try_auto_refresh()` from Task 5
- Produces: updated `health_check_loop` that calls `_try_auto_refresh` and resets `_alert_active` on success

- [ ] **Step 1: Write failing test**

Append to `tests/server/test_auto_refresh.py`:
```python
async def test_health_check_loop_resets_alert_on_auto_refresh_success(monkeypatch):
    """health_check_loop should reset _alert_active when auto-refresh succeeds."""
    import asyncio as _asyncio
    from familylink import SessionExpiredError
    from familylink_server.config import settings
    from familylink_server.main import health_check_loop

    monkeypatch.setattr(settings, 'cookie_refresher_url', 'http://sidecar:8080')

    svc = _make_service()
    call_count = 0

    async def fake_get_members():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise SessionExpiredError('expired')
        # Second call succeeds

    svc.get_members = fake_get_members

    notified_expired = []
    notified_restored = []

    class FakeNotifier:
        async def notify_session_expired(self):
            notified_expired.append(True)

        async def notify_session_restored(self):
            notified_restored.append(True)

    sleep_calls = []

    async def fake_sleep(n):
        sleep_calls.append(n)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError  # stop the loop after 2 iterations

    with (
        patch('familylink_server.main.asyncio.sleep', side_effect=fake_sleep),
        patch('familylink_server.main._try_auto_refresh', return_value=True) as mock_refresh,
        patch('familylink_server.services.family_link.FamilyLink'),
    ):
        try:
            await health_check_loop(svc, FakeNotifier(), interval=0)
        except asyncio.CancelledError:
            pass

    # Auto-refresh was called on first SessionExpiredError
    mock_refresh.assert_called_once_with(svc, mock_refresh.call_args[0][1])
    # auth_failed flag was set then cleared
    assert svc._auth_failed is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/server/test_auto_refresh.py::test_health_check_loop_resets_alert_on_auto_refresh_success -v
```
Expected: `FAILED` — `_try_auto_refresh` not yet called from `health_check_loop`

- [ ] **Step 3: Update `health_check_loop` in main.py**

Locate the `except SessionExpiredError` block in `health_check_loop` (currently lines 53–59). Replace:
```python
        except SessionExpiredError as exc:
            logger.warning("Health check: session expired — %s", exc)
            if not _alert_active:
                _alert_active = True
                service.set_auth_failed(True)
                if notifier:
                    await notifier.notify_session_expired()
```
With:
```python
        except SessionExpiredError as exc:
            logger.warning('Health check: session expired — %s', exc)
            if not _alert_active:
                _alert_active = True
                service.set_auth_failed(True)
                if notifier:
                    await notifier.notify_session_expired()
                if await _try_auto_refresh(service, notifier):
                    _alert_active = False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/server/test_auto_refresh.py::test_health_check_loop_resets_alert_on_auto_refresh_success -v
```
Expected: `PASSED`

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```
Expected: all tests `PASSED`

- [ ] **Step 6: Lint and commit**

```bash
ruff check --fix src tests && ruff format src tests
git add src/familylink_server/main.py tests/server/test_auto_refresh.py
git commit -m "feat: auto-refresh cookies via sidecar on session expiry in health_check_loop"
```

---

## Spec Coverage Self-Check

| Spec requirement | Task |
|-----------------|------|
| Sidecar separate Docker image | Task 4 (`Dockerfile.refresher`) |
| Same repo | Task 4 (root-level `Dockerfile.refresher`) |
| `pip install ".[refresher]"` — lean install | Task 4 |
| Playwright headless Chromium login | Task 4 (`_get_cookies_b64`) |
| TOTP via pyotp | Task 4 (`_get_cookies_b64`) |
| `_to_netscape` converter | Task 3 |
| `POST /refresh` → `{"cookies_b64": ...}` | Task 4 |
| `GET /health` | Task 3 |
| 400 if creds missing | Task 4 |
| 500 on Playwright failure | Task 4 |
| `reinit_with_cookies_b64()` sets B64, pops SAPISID | Task 2 |
| `_try_auto_refresh()` returns bool | Task 5 |
| No-op when `COOKIE_REFRESHER_URL` unset | Task 5 |
| `health_check_loop` calls `_try_auto_refresh` | Task 6 |
| `_alert_active` reset on success | Task 6 |
| Discord `notify_session_restored` on success | Task 5 |
| Graceful degradation on failure | Task 5 (returns False, logs error) |

All requirements covered. ✓
