# Live-Browser Cookie Refresher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the doomed snapshot-replay cookie refresher with one that reads cookies from a persistent, logged-in Firefox container so the Google session never goes stale.

**Architecture:** A persistent `firefox` container holds a live parent-Google session (one-time noVNC login, self-warms). A rewritten `cookie-refresher` sidecar reads that profile's live `cookies.sqlite` via `browser_cookie3.firefox`, verifies against `kidsmanagement-pa`, and returns `cookies_b64` over the existing `POST /refresh` contract. The web app hot-reloads via `reinit_with_cookies_b64`, refreshes proactively every 12h, and backs off (no more 500-loops) on a dead session.

**Tech Stack:** Python 3.12, FastAPI, `browser_cookie3` (firefox backend), `linuxserver/firefox` (noVNC), Docker Compose, httpx, pytest (asyncio auto mode).

## Global Constraints

- Python 3.12; virtualenv in `.venv`; use `pip` and `python -m pytest` — never `uv`.
- Ruff: Google docstring convention, single-quoted inline strings, isort.
- `asyncio_mode = "auto"` — `async def test_*` are awaited automatically.
- Server tests set env in `tests/server/conftest.py` before importing the app.
- The `POST /refresh` contract (X-Api-Key header → `{"cookies_b64": str}`) is UNCHANGED; the web app's `_try_auto_refresh` keeps calling it as-is.
- The `firefox` noVNC UI grants full Google-account access — it must be behind auth and never publicly exposed (documented, not code-enforced here).
- Keep `_verify_family_link_access` as the real liveness gate. No weak "SAPISID present" success path.

---

## File Structure

- `pyproject.toml` — `refresher` extra: drop `playwright`, add `browser-cookie3`.
- `Dockerfile.refresher` — remove Playwright/Chromium install; tiny image.
- `src/familylink_server/cookie_refresher_app.py` — **rewritten**: `/refresh` reads live Firefox profile; delete `/bootstrap`, `StorageState`, `_get_cookies_b64`, `_cookiejar`/Playwright code.
- `src/familylink_server/routers/admin.py` — remove obsolete `/refresher-bootstrap` proxy.
- `src/familylink_server/config.py` — add `firefox_novnc_url`.
- `src/familylink_server/main.py` — backoff in `_try_auto_refresh`; new `proactive_refresh_loop`; noVNC URL in 503 page.
- `tests/server/test_cookie_refresher.py` — **rewritten** for the live-profile reader.
- `tests/server/test_auto_refresh.py` — **new**: backoff + proactive loop.
- `scripts/bootstrap_refresher_session.py` — **deleted**.
- `docker-compose.yml` — add `firefox` service + `firefox_profile` volume; refresher mounts profile read-only.
- `README.md` — replace snapshot bootstrap docs with noVNC login procedure + security warning.

---

### Task 1: Refresher dependencies + image (drop Playwright)

**Files:**
- Modify: `pyproject.toml` (`[project.optional-dependencies].refresher`)
- Modify: `Dockerfile.refresher`

**Interfaces:**
- Consumes: nothing.
- Produces: a `refresher` extra that installs `browser-cookie3` (firefox reader) and FastAPI/uvicorn; an image without Playwright.

- [ ] **Step 1: Update the `refresher` extra**

In `pyproject.toml`, replace the `refresher` list:

```toml
refresher = ["browser-cookie3>=0.19.1", "fastapi>=0.115", "uvicorn[standard]>=0.32"]
```

- [ ] **Step 2: Rewrite `Dockerfile.refresher`**

Replace the whole file with:

```dockerfile
# Sidecar image: reads cookies from the persistent Firefox profile volume.
FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[refresher]"

ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FIREFOX_PROFILE_DIR=/profile

EXPOSE 8080
CMD ["uvicorn", "familylink_server.cookie_refresher_app:app", \
     "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 3: Verify the extra resolves**

Run: `pip install -e ".[refresher]" && python -c "import browser_cookie3; print('ok')"`
Expected: prints `ok`, no Playwright installed.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml Dockerfile.refresher
git commit -m "build: refresher reads firefox profile, drop playwright"
```

---

### Task 2: Rewrite the refresher to read the live Firefox profile

**Files:**
- Modify (rewrite): `src/familylink_server/cookie_refresher_app.py`
- Test: `tests/server/test_cookie_refresher.py` (rewritten in Task 3; this task adds the first new tests)

**Interfaces:**
- Consumes: `browser_cookie3.firefox(cookie_file=...)`; `familylink.FamilyLink` (via `_verify_family_link_access`).
- Produces:
  - `app: FastAPI`
  - `GET /health` → `{"status": "ok"}`
  - `POST /refresh` (X-Api-Key) → `{"cookies_b64": str}`; `403` wrong key; `409` not logged in / no SAPISID; `502` dead session.
  - `_profile_cookie_file() -> pathlib.Path | None` — first `cookies.sqlite` under `FIREFOX_PROFILE_DIR` (default `/profile`), or `None`.
  - `_read_live_google_cookies(sqlite_path) -> list` — jar cookies with `google.com` in domain; raises `NotLoggedInError` if no SAPISID.
  - `_jar_to_netscape(cookies) -> str`
  - `_verify_family_link_access(cookies_b64: str) -> None` (kept, unchanged behavior)
  - `class NotLoggedInError(Exception)`

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_cookie_refresher.py` with:

```python
"""Tests for the live-profile cookie-refresher sidecar."""

import base64

from fastapi.testclient import TestClient


class _FakeCookie:
    def __init__(self, name, value='v', domain='.google.com', path='/', secure=True, expires=0):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path
        self.secure = secure
        self.expires = expires


def _client(monkeypatch, tmp_path, jar, verify_ok=True):
    profile = tmp_path / 'profile'
    profile.mkdir()
    (profile / 'cookies.sqlite').write_bytes(b'')  # existence only; reader is patched
    monkeypatch.setenv('FIREFOX_PROFILE_DIR', str(profile))
    import familylink_server.cookie_refresher_app as app_mod

    monkeypatch.setattr(app_mod.browser_cookie3, 'firefox', lambda **kw: jar)
    if verify_ok:
        monkeypatch.setattr(app_mod, '_verify_family_link_access', lambda b64: None)
    else:
        def _boom(b64):
            raise RuntimeError('Refreshed cookies failed Family Link API verification: HTTP 401')
        monkeypatch.setattr(app_mod, '_verify_family_link_access', _boom)
    return TestClient(app_mod.app)


def test_refresh_returns_cookies_b64(monkeypatch, tmp_path):
    jar = [_FakeCookie('SAPISID'), _FakeCookie('SID', secure=False)]
    client = _client(monkeypatch, tmp_path, jar)
    resp = client.post('/refresh')
    assert resp.status_code == 200
    b64 = resp.json()['cookies_b64']
    text = base64.b64decode(b64).decode()
    assert 'SAPISID' in text
    assert text.startswith('# Netscape HTTP Cookie File')
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/server/test_cookie_refresher.py::test_refresh_returns_cookies_b64 -v`
Expected: FAIL (module still has old Playwright API / no `browser_cookie3` attribute).

- [ ] **Step 3: Rewrite the module**

Replace the entire contents of `src/familylink_server/cookie_refresher_app.py` with:

```python
"""Sidecar: reads cookies from a persistent, logged-in Firefox profile."""

import base64
import logging
import os
from collections.abc import Iterable
from pathlib import Path

import browser_cookie3
from fastapi import FastAPI, Header, HTTPException

logger = logging.getLogger(__name__)

app = FastAPI(title='cookie-refresher')


class NotLoggedInError(Exception):
    """Raised when the Firefox profile has no usable Google session."""


@app.get('/health')
async def health() -> dict:
    """Liveness probe."""
    return {'status': 'ok'}


def _profile_cookie_file() -> Path | None:
    """Return the first cookies.sqlite under FIREFOX_PROFILE_DIR, or None."""
    root = Path(os.environ.get('FIREFOX_PROFILE_DIR', '/profile'))
    if not root.exists():
        return None
    return next(iter(sorted(root.rglob('cookies.sqlite'))), None)


def _read_live_google_cookies(sqlite_path: Path) -> list:
    """Read google.com cookies from the live Firefox profile.

    Raises:
        NotLoggedInError: if the profile holds no SAPISID cookie.
    """
    jar = browser_cookie3.firefox(cookie_file=str(sqlite_path), domain_name='google.com')
    cookies = [c for c in jar if 'google.com' in c.domain]
    if not any(c.name == 'SAPISID' for c in cookies):
        raise NotLoggedInError('Firefox profile has no SAPISID — sign in via noVNC.')
    return cookies


def _jar_to_netscape(cookies: Iterable) -> str:
    """Convert browser_cookie3 cookie objects to Netscape cookies.txt format."""
    lines = ['# Netscape HTTP Cookie File']
    for c in cookies:
        sub = 'TRUE' if c.domain.startswith('.') else 'FALSE'
        secure = 'TRUE' if c.secure else 'FALSE'
        exp = int(c.expires or 0)
        lines.append(
            f'{c.domain}\t{sub}\t{c.path}\t{secure}\t{exp}\t{c.name}\t{c.value}'
        )
    return '\n'.join(lines) + '\n'


def _verify_family_link_access(cookies_b64: str) -> None:
    """Confirm the cookies authenticate against the Family Link API.

    myaccount.google.com accepts sessions that kidsmanagement-pa rejects, so a
    real API call is the only trustworthy liveness check.
    """
    from familylink import FamilyLink

    prev_b64 = os.environ.get('FAMILYLINK_COOKIES_B64')
    prev_sapisid = os.environ.pop('FAMILYLINK_SAPISID', None)
    os.environ['FAMILYLINK_COOKIES_B64'] = cookies_b64
    try:
        FamilyLink().get_members()
    except Exception as exc:
        raise RuntimeError(
            f'Refreshed cookies failed Family Link API verification: {exc}'
        ) from exc
    finally:
        if prev_b64 is None:
            os.environ.pop('FAMILYLINK_COOKIES_B64', None)
        else:
            os.environ['FAMILYLINK_COOKIES_B64'] = prev_b64
        if prev_sapisid is not None:
            os.environ['FAMILYLINK_SAPISID'] = prev_sapisid


@app.post('/refresh')
async def refresh(x_api_key: str = Header(default='')) -> dict:
    """Read live cookies from the Firefox profile; verify; return base64."""
    expected = os.environ.get('REFRESHER_API_KEY', '')
    if expected and x_api_key != expected:
        raise HTTPException(403, 'Forbidden')

    sqlite_path = _profile_cookie_file()
    if sqlite_path is None:
        raise HTTPException(409, 'Firefox profile not initialised — sign in via noVNC.')

    try:
        cookies = _read_live_google_cookies(sqlite_path)
    except NotLoggedInError as exc:
        raise HTTPException(409, str(exc)) from exc

    cookies_b64 = base64.b64encode(_jar_to_netscape(cookies).encode()).decode()
    try:
        _verify_family_link_access(cookies_b64)
    except Exception as exc:
        logger.error('Refresh failed: %s', exc)
        raise HTTPException(502, str(exc)) from exc

    logger.info('Refresh: returned %d live google.com cookies', len(cookies))
    return {'cookies_b64': cookies_b64}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/server/test_cookie_refresher.py::test_refresh_returns_cookies_b64 -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/cookie_refresher_app.py tests/server/test_cookie_refresher.py
git commit -m "feat: refresher reads live firefox profile instead of replaying snapshot"
```

---

### Task 3: Refresher error paths + remove bootstrap

**Files:**
- Modify: `tests/server/test_cookie_refresher.py`
- Modify: `src/familylink_server/routers/admin.py`
- Delete: `scripts/bootstrap_refresher_session.py`

**Interfaces:**
- Consumes: `cookie_refresher_app` surface from Task 2.
- Produces: `admin.py` with the `/refresher-bootstrap` route removed (keeps the module + router import intact).

- [ ] **Step 1: Write the failing error-path tests**

Append to `tests/server/test_cookie_refresher.py`:

```python
def test_refresh_forbidden_when_wrong_key(monkeypatch, tmp_path):
    monkeypatch.setenv('REFRESHER_API_KEY', 'secret')
    jar = [_FakeCookie('SAPISID')]
    client = _client(monkeypatch, tmp_path, jar)
    resp = client.post('/refresh', headers={'X-Api-Key': 'wrong'})
    assert resp.status_code == 403


def test_refresh_409_when_no_profile(monkeypatch, tmp_path):
    monkeypatch.setenv('FIREFOX_PROFILE_DIR', str(tmp_path / 'missing'))
    import familylink_server.cookie_refresher_app as app_mod

    resp = TestClient(app_mod.app).post('/refresh')
    assert resp.status_code == 409


def test_refresh_409_when_no_sapisid(monkeypatch, tmp_path):
    jar = [_FakeCookie('NID')]  # no SAPISID
    client = _client(monkeypatch, tmp_path, jar)
    resp = client.post('/refresh')
    assert resp.status_code == 409


def test_refresh_502_when_session_dead(monkeypatch, tmp_path):
    jar = [_FakeCookie('SAPISID')]
    client = _client(monkeypatch, tmp_path, jar, verify_ok=False)
    resp = client.post('/refresh')
    assert resp.status_code == 502
    assert 'verification' in resp.json()['detail']
```

- [ ] **Step 2: Run to verify they pass**

Run: `python -m pytest tests/server/test_cookie_refresher.py -v`
Expected: all PASS (the module from Task 2 already implements these paths).

- [ ] **Step 3: Remove the obsolete admin bootstrap proxy**

In `src/familylink_server/routers/admin.py`, delete the entire `refresher_bootstrap` route function (the `@router.post('/refresher-bootstrap', ...)` handler) and any now-unused imports (`Request`, `httpx`) if nothing else uses them. Keep `router` defined and exported.

- [ ] **Step 4: Delete the bootstrap script**

Run: `git rm scripts/bootstrap_refresher_session.py`

- [ ] **Step 5: Run the full server test suite**

Run: `python -m pytest tests/server/ -q`
Expected: PASS (no test references the deleted script or route; if one does, delete that test — it covers removed behavior).

- [ ] **Step 6: Commit**

```bash
git add tests/server/test_cookie_refresher.py src/familylink_server/routers/admin.py
git commit -m "feat: refresher error paths; remove snapshot bootstrap"
```

---

### Task 4: Backoff in `_try_auto_refresh` (stop the 500-loop)

**Files:**
- Modify: `src/familylink_server/main.py`
- Test: `tests/server/test_auto_refresh.py` (new)

**Interfaces:**
- Consumes: `settings.cookie_refresher_url`, `httpx`.
- Produces: module-level `_reset_refresh_backoff()` (test helper) and backoff behavior inside `_try_auto_refresh` — a failed refresh sets an exponential cooldown (60s → 3600s cap) during which further calls short-circuit to `False` without hitting the sidecar; a success resets it.

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_auto_refresh.py`:

```python
"""Tests for auto-refresh backoff and the proactive refresh loop."""

import familylink_server.main as main


async def test_backoff_skips_sidecar_after_failure(monkeypatch, httpx_mock):
    monkeypatch.setattr(main.settings, 'cookie_refresher_url', 'http://cr:8080')
    main._reset_refresh_backoff()
    httpx_mock.add_response(url='http://cr:8080/refresh', status_code=500)

    class _Svc:
        def set_auth_failed(self, v):
            pass

    ok1 = await main._try_auto_refresh(_Svc(), None)
    ok2 = await main._try_auto_refresh(_Svc(), None)  # immediately again

    assert ok1 is False and ok2 is False
    # sidecar hit only once; the second call was suppressed by backoff
    assert len(httpx_mock.get_requests()) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/server/test_auto_refresh.py::test_backoff_skips_sidecar_after_failure -v`
Expected: FAIL (`_reset_refresh_backoff` undefined; second call hits sidecar → 2 requests).

- [ ] **Step 3: Add backoff to `main.py`**

Near the top of `src/familylink_server/main.py`, after the imports, add:

```python
import time

_refresh_lock = asyncio.Lock()
_refresh_backoff_until = 0.0
_refresh_backoff_seconds = 0.0
_BACKOFF_START = 60.0
_BACKOFF_CAP = 3600.0


def _reset_refresh_backoff() -> None:
    """Clear auto-refresh backoff state (also used by tests)."""
    global _refresh_backoff_until, _refresh_backoff_seconds
    _refresh_backoff_until = 0.0
    _refresh_backoff_seconds = 0.0
```

(If `_refresh_lock = asyncio.Lock()` already exists lower in the file, remove that duplicate so the lock is defined only once, here.)

Then change `_try_auto_refresh` so its body reads:

```python
async def _try_auto_refresh(
    service: 'FamilyLinkService',
    notifier: 'DiscordNotifier | None',
) -> bool:
    """Call cookie-refresher sidecar; hot-reload service. Returns True on success."""
    global _refresh_backoff_until, _refresh_backoff_seconds
    url = settings.cookie_refresher_url
    if not url:
        return False
    if time.monotonic() < _refresh_backoff_until:
        logger.info('Auto-refresh: in backoff, skipping')
        return False
    if _refresh_lock.locked():
        logger.info('Auto-refresh: already in progress, skipping')
        return False
    async with _refresh_lock:
        try:
            logger.info('Auto-refresh: calling sidecar at %s/refresh', url)
            headers = {}
            if settings.refresher_api_key:
                headers['X-Api-Key'] = settings.refresher_api_key
            async with httpx.AsyncClient() as client:
                resp = await client.post(f'{url}/refresh', timeout=120, headers=headers)
                resp.raise_for_status()
            cookies_b64 = resp.json()['cookies_b64']
            service.reinit_with_cookies_b64(cookies_b64)
            await service.get_members()
            service.set_auth_failed(False)
            if notifier:
                await notifier.notify_session_restored()
            _refresh_backoff_until = 0.0
            _refresh_backoff_seconds = 0.0
            logger.info('Auto-refresh: success')
            return True
        except Exception as exc:
            logger.error('Auto-refresh: failed — %s', exc)
            _refresh_backoff_seconds = min(
                _BACKOFF_CAP,
                _refresh_backoff_seconds * 2 if _refresh_backoff_seconds else _BACKOFF_START,
            )
            _refresh_backoff_until = time.monotonic() + _refresh_backoff_seconds
            return False
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/server/test_auto_refresh.py::test_backoff_skips_sidecar_after_failure -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/main.py tests/server/test_auto_refresh.py
git commit -m "feat: exponential backoff on failed auto-refresh"
```

---

### Task 5: Proactive refresh loop (rotate before expiry)

**Files:**
- Modify: `src/familylink_server/main.py`
- Test: `tests/server/test_auto_refresh.py`

**Interfaces:**
- Consumes: `_try_auto_refresh` (Task 4).
- Produces: `async def proactive_refresh_loop(service, notifier, interval=43200)` — sleeps `interval` seconds then calls `_try_auto_refresh`, forever. Started as a task in `lifespan` and cancelled on shutdown.

- [ ] **Step 1: Write the failing test**

Append to `tests/server/test_auto_refresh.py`:

```python
import asyncio


async def test_proactive_loop_calls_refresh(monkeypatch):
    calls = []

    async def _fake_refresh(service, notifier):
        calls.append(True)
        return True

    monkeypatch.setattr(main, '_try_auto_refresh', _fake_refresh)
    task = asyncio.create_task(main.proactive_refresh_loop(object(), None, interval=0))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert calls, 'proactive loop should have called _try_auto_refresh at least once'
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/server/test_auto_refresh.py::test_proactive_loop_calls_refresh -v`
Expected: FAIL (`proactive_refresh_loop` undefined).

- [ ] **Step 3: Add the loop and wire it into lifespan**

In `src/familylink_server/main.py`, add after `_try_auto_refresh`:

```python
async def proactive_refresh_loop(
    service: 'FamilyLinkService',
    notifier: 'DiscordNotifier | None',
    interval: int = 43200,
) -> None:
    """Refresh cookies from the live browser every `interval` seconds.

    The Firefox session is always fresh, so rotating well before natural cookie
    expiry means a hard 401 is never reached.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            await _try_auto_refresh(service, notifier)
        except Exception as exc:  # never let the loop die
            logger.warning('Proactive refresh error (transient): %s', exc)
```

In `lifespan`, alongside the other `asyncio.create_task(...)` calls, add:

```python
    proactive_task = asyncio.create_task(
        proactive_refresh_loop(get_service(), notifier)
    )
    logger.info('Proactive cookie-refresh loop started (interval=43200s)')
```

and in the shutdown section (after `yield`), mirror the existing cancel pattern:

```python
    proactive_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await proactive_task
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/server/test_auto_refresh.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/main.py tests/server/test_auto_refresh.py
git commit -m "feat: proactive 12h cookie refresh loop"
```

---

### Task 6: noVNC URL in config + expired-session page

**Files:**
- Modify: `src/familylink_server/config.py`
- Modify: `src/familylink_server/main.py` (the `SessionExpiredError` HTML handler)
- Test: `tests/server/test_auto_refresh.py`

**Interfaces:**
- Consumes: `settings.firefox_novnc_url`.
- Produces: `Settings.firefox_novnc_url: str = ''`; the 503 page includes the noVNC login link when the setting is non-empty.

- [ ] **Step 1: Write the failing test**

Append to `tests/server/test_auto_refresh.py`:

```python
from fastapi.testclient import TestClient


def test_expired_page_shows_novnc_link(monkeypatch):
    monkeypatch.setattr(main.settings, 'firefox_novnc_url', 'https://ff.example')
    from familylink import SessionExpiredError

    @main.app.get('/_boom_test')
    async def _boom():  # noqa: ANN202
        raise SessionExpiredError('HTTP 401')

    resp = TestClient(main.app, raise_server_exceptions=False).get('/_boom_test')
    assert resp.status_code == 503
    assert 'https://ff.example' in resp.text
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/server/test_auto_refresh.py::test_expired_page_shows_novnc_link -v`
Expected: FAIL (noVNC URL absent from page; attribute may be missing).

- [ ] **Step 3: Add the setting**

In `src/familylink_server/config.py`, add after `refresher_api_key`:

```python
    firefox_novnc_url: str = ''
```

- [ ] **Step 4: Include the link in the 503 handler**

In `src/familylink_server/main.py`, inside `session_expired_handler`, before the `return HTMLResponse(...)`, add:

```python
    novnc = settings.firefox_novnc_url
    novnc_block = (
        f'<p>If auto-refresh cannot restore the session, sign back into Google in '
        f'the refresher browser: <a href="{novnc}">{novnc}</a></p>'
        if novnc
        else ''
    )
```

Then make the returned HTML an f-string: change the opening `content="""` to `content=f"""` and insert the placeholder line `{novnc_block}` on its own line immediately after the existing auto-refresh paragraph (`<p>If the <code>cookie-refresher</code> sidecar ...</p>`). The HTML literal contains no other `{`/`}` characters, so the f-string conversion is safe.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/server/test_auto_refresh.py::test_expired_page_shows_novnc_link -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/config.py src/familylink_server/main.py tests/server/test_auto_refresh.py
git commit -m "feat: surface noVNC login link on session-expired page"
```

---

### Task 7: Compose — Firefox container + shared profile volume

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: a `firefox` service holding the live session; `firefox_profile` volume mounted read-only into `cookie-refresher` at `/profile`; refresher gains `FIREFOX_PROFILE_DIR=/profile` and `depends_on: firefox`.

- [ ] **Step 1: Add the `firefox` service and volume**

In `docker-compose.yml`, add a new service:

```yaml
  firefox:
    image: lscr.io/linuxserver/firefox:latest
    restart: unless-stopped
    shm_size: "1gb"
    environment:
      PUID: "1000"
      PGID: "1000"
      TZ: Etc/UTC
    volumes:
      - firefox_profile:/config
    # noVNC UI on 3000 — expose ONLY behind auth (Traefik basic-auth) or keep
    # internal and reach it via SSH tunnel. NEVER expose publicly.
```

Update the `cookie-refresher` service to read the profile:

```yaml
  cookie-refresher:
    build:
      context: .
      dockerfile: Dockerfile.refresher
    restart: unless-stopped
    environment:
      REFRESHER_API_KEY: ${REFRESHER_API_KEY:-}
      FIREFOX_PROFILE_DIR: /profile
    volumes:
      - firefox_profile:/profile:ro
    depends_on:
      - firefox
```

Add the volume under `volumes:`:

```yaml
  firefox_profile:
```

Remove the now-unused `refresher_state` volume (and its mount on `cookie-refresher`, replaced above).

- [ ] **Step 2: Validate compose syntax**

Run: `docker compose config >/dev/null && echo "compose ok"`
Expected: prints `compose ok` (no YAML/schema errors). If Docker is unavailable locally, run `python -c "import yaml,sys; yaml.safe_load(open('docker-compose.yml')); print('yaml ok')"`.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add persistent firefox container + shared profile volume"
```

---

### Task 8: Docs — noVNC login procedure + security; retire snapshot docs

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: README reflecting the live-browser model.

- [ ] **Step 1: Replace the "Auto-refresh sidecar" section**

In `README.md`, replace the "Auto-refresh sidecar (recommended)" section and its ASCII diagram, plus the "Deploying the sidecar in Coolify" steps that reference `bootstrap_refresher_session.py`, with a description of the live-browser model:

- A persistent `firefox` container holds the parent Google session.
- **One-time login:** open the protected noVNC UI, sign into the parent Google account normally (headful, so Google allows it). The profile persists on `firefox_profile`.
- The `cookie-refresher` reads the live `cookies.sqlite` on demand (`POST /refresh`) and the web app hot-reloads; a proactive loop refreshes every 12h.
- Re-login is needed only on a real session death (password change, sign-out, security event).

Set `FIREFOX_NOVNC_URL` on the web service so the session-expired page links to the login UI.

- [ ] **Step 2: Add the security warning**

In the auth/security section, add a bold warning: the `firefox` noVNC UI grants full access to the parent Google account and its profile volume stores live session tokens — it MUST be behind authentication (e.g. Traefik basic-auth) and never publicly exposed; prefer internal-only access via SSH tunnel.

- [ ] **Step 3: Fix the troubleshooting table**

Update the "Google/Family Link session problems" table: the `verification: HTTP 401` row's fix becomes "sign back in via the noVNC UI" (not re-run bootstrap). Keep the `export-cookies --coolify --restart` row as the always-works manual fallback. Remove references to `bootstrap_refresher_session.py`.

- [ ] **Step 4: Verify no stale references remain**

Run: `grep -rn "bootstrap_refresher_session\|state.json\|storage_state" README.md`
Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: live-browser refresher setup, noVNC login, security"
```

---

## Final verification

- [ ] Run the full suite: `python -m pytest -q` — expected: PASS.
- [ ] Lint: `ruff check src tests` and `ruff format --check src tests` — expected: clean.
- [ ] Types: `mypy src` — expected: no new errors.
- [ ] Run `graphify update .` to refresh the knowledge graph.

## Deferred to deployment (not code — tracked in the spec)

- **Spike (validates the core assumption):** stand up the `firefox` container, log into the parent account via noVNC, `curl -H "X-Api-Key: <key>" http://cookie-refresher:8080/refresh` → confirm `{cookies_b64}` and that the web app hot-reloads. **Re-verify after 2-3 days** the warm session still authenticates. If it decays, add an explicit keep-alive reload (pinned auto-reloading Google tab or an in-container cron) and re-test.
- **WAL note:** Firefox uses SQLite WAL; `browser_cookie3` copies `cookies.sqlite` and may miss the newest WAL writes. If refreshes read slightly stale cookies, force a checkpoint or read `-wal` too. Validate in the spike.
```
