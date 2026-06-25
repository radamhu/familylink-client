# Coolify Cookie Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--coolify` and `--restart` flags to `familylink export-cookies --base64` that push the new `FAMILYLINK_COOKIES_B64` value to the Coolify-hosted app via REST API.

**Architecture:** A new `_push_to_coolify` helper in `cli.py` owns all Coolify HTTP logic and is tested in isolation. `_cmd_export_cookies` gains two new argparse flags whose validation (flag combinations + env var presence) runs before any browser interaction. The Coolify API call happens at the end of the existing `--base64` block, after the local `.env` update.

**Tech Stack:** Python stdlib (`os`, `argparse`), `httpx` (already a project dependency), `pytest` + `unittest.mock`.

## Global Constraints

- Python 3.12, `pip` only (no `uv`)
- Run tests with `python -m pytest`, lint with `ruff check src tests`, format with `ruff format src tests`
- `httpx` is already installed — do not add new dependencies
- Do not import anything from `familylink_server` in `cli.py`
- All new env vars read via `os.environ.get()` — not pydantic-settings

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/familylink/cli.py` | Add imports, `_push_to_coolify` helper, two new argparse flags, validation, and call site |
| Modify | `.env.example` | Document the three new Coolify env vars |
| Modify | `.env` | Add actual Coolify values for local dev |
| Create | `tests/unit/test_cli_coolify.py` | Unit tests for `_push_to_coolify` and flag validation |

---

### Task 1: Add Coolify env vars to config files

**Files:**
- Modify: `.env.example`
- Modify: `.env`

**Interfaces:**
- Produces: `COOLIFY_URL`, `COOLIFY_TOKEN`, `COOLIFY_APP_UUID` documented and available in shell

- [ ] **Step 1: Add Coolify section to `.env.example`**

Append this block after the Discord section (end of file):

```
# ------------------------------------------
# Coolify integration (optional — used by `familylink export-cookies --coolify`)
# ------------------------------------------

# Base URL of your Coolify instance
# COOLIFY_URL=http://192.168.0.22:8000

# Coolify API bearer token (Settings → API Tokens)
# COOLIFY_TOKEN=<your-token>

# UUID of the familylink-client application in Coolify
# (visible in the app URL: /project/.../application/<uuid>)
# COOLIFY_APP_UUID=<your-app-uuid>
```

- [ ] **Step 2: Add actual Coolify values to `.env`**

Add these lines to `.env` (create the section if it doesn't exist yet):

```
COOLIFY_URL=http://192.168.0.22:8000
COOLIFY_TOKEN=1|EWfPB7l6oCiHpZ6n93ptCMyXfA7gKZiqOrHaZqPJ4c2c35cc
COOLIFY_APP_UUID=ou4t4la0sfos78d8z3aytvah
```

- [ ] **Step 3: Commit**

```bash
git add .env.example .env
git commit -m "config: add Coolify API env vars for cookie sync"
```

---

### Task 2: Implement `_push_to_coolify` helper and unit tests

**Files:**
- Modify: `src/familylink/cli.py:1-10` (add imports)
- Modify: `src/familylink/cli.py:55` (add helper before `_cmd_export_cookies`)
- Create: `tests/unit/test_cli_coolify.py`

**Interfaces:**
- Produces: `_push_to_coolify(base64_value: str, url: str, token: str, app_uuid: str, *, restart: bool) -> None`
  - Calls `httpx.patch(...)` then optionally `httpx.get(...)`
  - On any failure: prints `[error]...[/error]` and calls `sys.exit(1)`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_cli_coolify.py`:

```python
"""Unit tests for Coolify push helper in familylink.cli."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from familylink.cli import _push_to_coolify


def _resp(is_success=True, status_code=200, text="ok"):
    r = MagicMock()
    r.is_success = is_success
    r.status_code = status_code
    r.text = text
    return r


@patch("familylink.cli.httpx")
def test_push_patches_env_var(mock_httpx):
    mock_httpx.patch.return_value = _resp()
    _push_to_coolify("b64val", "http://coolify:8000", "tok", "app-uuid", restart=False)
    mock_httpx.patch.assert_called_once_with(
        "http://coolify:8000/api/v1/applications/app-uuid/envs",
        headers={"Authorization": "Bearer tok"},
        json={"key": "FAMILYLINK_COOKIES_B64", "value": "b64val", "is_preview": False},
    )
    mock_httpx.get.assert_not_called()


@patch("familylink.cli.httpx")
def test_push_does_not_restart_by_default(mock_httpx):
    mock_httpx.patch.return_value = _resp()
    _push_to_coolify("b64val", "http://coolify:8000", "tok", "app-uuid", restart=False)
    mock_httpx.get.assert_not_called()


@patch("familylink.cli.httpx")
def test_push_restarts_when_requested(mock_httpx):
    mock_httpx.patch.return_value = _resp()
    mock_httpx.get.return_value = _resp()
    _push_to_coolify("b64val", "http://coolify:8000", "tok", "app-uuid", restart=True)
    mock_httpx.get.assert_called_once_with(
        "http://coolify:8000/api/v1/applications/app-uuid/restart",
        headers={"Authorization": "Bearer tok"},
    )


@patch("familylink.cli.httpx")
def test_push_exits_on_patch_api_error(mock_httpx):
    mock_httpx.patch.return_value = _resp(is_success=False, status_code=401, text="Unauthorized")
    with pytest.raises(SystemExit) as exc:
        _push_to_coolify("b64val", "http://coolify:8000", "tok", "app-uuid", restart=False)
    assert exc.value.code == 1


@patch("familylink.cli.httpx")
def test_push_exits_on_restart_api_error(mock_httpx):
    mock_httpx.patch.return_value = _resp()
    mock_httpx.get.return_value = _resp(is_success=False, status_code=500, text="Server Error")
    with pytest.raises(SystemExit) as exc:
        _push_to_coolify("b64val", "http://coolify:8000", "tok", "app-uuid", restart=True)
    assert exc.value.code == 1


@patch("familylink.cli.httpx")
def test_push_exits_on_patch_network_error(mock_httpx):
    mock_httpx.patch.side_effect = httpx.RequestError("Connection refused")
    mock_httpx.RequestError = httpx.RequestError
    with pytest.raises(SystemExit) as exc:
        _push_to_coolify("b64val", "http://coolify:8000", "tok", "app-uuid", restart=False)
    assert exc.value.code == 1


@patch("familylink.cli.httpx")
def test_push_exits_on_restart_network_error(mock_httpx):
    mock_httpx.patch.return_value = _resp()
    mock_httpx.get.side_effect = httpx.RequestError("Connection refused")
    mock_httpx.RequestError = httpx.RequestError
    with pytest.raises(SystemExit) as exc:
        _push_to_coolify("b64val", "http://coolify:8000", "tok", "app-uuid", restart=True)
    assert exc.value.code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/test_cli_coolify.py -v
```

Expected: `ImportError` or `7 failed` — `_push_to_coolify` does not exist yet.

- [ ] **Step 3: Add imports to `cli.py`**

In `src/familylink/cli.py`, add `import httpx` and `import os` to the stdlib imports block (after `import base64`, before `import csv`):

```python
import argparse
import base64
import csv
import httpx
import logging
import os
import sys
from datetime import datetime
from http.cookiejar import MozillaCookieJar
from pathlib import Path
```

- [ ] **Step 4: Add `_push_to_coolify` to `cli.py`**

Insert this function immediately before `_cmd_export_cookies` (before line 55):

```python
def _push_to_coolify(base64_value: str, url: str, token: str, app_uuid: str, *, restart: bool) -> None:
    """Push FAMILYLINK_COOKIES_B64 to Coolify and optionally restart the app."""
    headers = {'Authorization': f'Bearer {token}'}
    try:
        resp = httpx.patch(
            f'{url}/api/v1/applications/{app_uuid}/envs',
            headers=headers,
            json={'key': 'FAMILYLINK_COOKIES_B64', 'value': base64_value, 'is_preview': False},
        )
    except httpx.RequestError as exc:
        console.print(f'[error]Coolify network error:[/error] {exc}')
        sys.exit(1)
    if not resp.is_success:
        console.print(f'[error]Coolify API error {resp.status_code}:[/error] {resp.text}')
        sys.exit(1)
    console.print('[success]Updated FAMILYLINK_COOKIES_B64 in Coolify[/success]')

    if restart:
        try:
            resp = httpx.get(
                f'{url}/api/v1/applications/{app_uuid}/restart',
                headers=headers,
            )
        except httpx.RequestError as exc:
            console.print(f'[error]Coolify restart network error:[/error] {exc}')
            sys.exit(1)
        if not resp.is_success:
            console.print(f'[error]Coolify restart error {resp.status_code}:[/error] {resp.text}')
            sys.exit(1)
        console.print('[success]Restarted familylink-client in Coolify[/success]')
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_cli_coolify.py -v
```

Expected: `7 passed`.

- [ ] **Step 6: Lint and format**

```bash
ruff check src tests && ruff format src tests
```

Fix any issues reported.

- [ ] **Step 7: Commit**

```bash
git add src/familylink/cli.py tests/unit/test_cli_coolify.py
git commit -m "feat: add _push_to_coolify helper with unit tests"
```

---

### Task 3: Wire `--coolify` and `--restart` flags into `_cmd_export_cookies`

**Files:**
- Modify: `src/familylink/cli.py` — `_cmd_export_cookies` function
- Modify: `tests/unit/test_cli_coolify.py` — add flag validation tests

**Interfaces:**
- Consumes: `_push_to_coolify(base64_value, url, token, app_uuid, *, restart)` from Task 2
- Produces: updated CLI command with `--coolify` / `--restart` flags

- [ ] **Step 1: Write failing flag-validation tests**

Append to `tests/unit/test_cli_coolify.py`:

```python
from familylink.cli import _cmd_export_cookies


def test_coolify_requires_base64():
    """--coolify without --base64 must exit 1 before touching browser."""
    with pytest.raises(SystemExit) as exc:
        _cmd_export_cookies(["--coolify"])
    assert exc.value.code == 1


def test_restart_requires_coolify():
    """--restart without --coolify must exit 1 before touching browser."""
    with pytest.raises(SystemExit) as exc:
        _cmd_export_cookies(["--restart"])
    assert exc.value.code == 1


def test_coolify_exits_on_missing_coolify_url(monkeypatch):
    """--coolify exits 1 when COOLIFY_URL is absent, before touching browser."""
    monkeypatch.delenv("COOLIFY_URL", raising=False)
    monkeypatch.setenv("COOLIFY_TOKEN", "tok")
    monkeypatch.setenv("COOLIFY_APP_UUID", "uuid")
    with pytest.raises(SystemExit) as exc:
        _cmd_export_cookies(["--base64", "--coolify"])
    assert exc.value.code == 1


def test_coolify_exits_on_missing_coolify_token(monkeypatch):
    """--coolify exits 1 when COOLIFY_TOKEN is absent, before touching browser."""
    monkeypatch.setenv("COOLIFY_URL", "http://coolify:8000")
    monkeypatch.delenv("COOLIFY_TOKEN", raising=False)
    monkeypatch.setenv("COOLIFY_APP_UUID", "uuid")
    with pytest.raises(SystemExit) as exc:
        _cmd_export_cookies(["--base64", "--coolify"])
    assert exc.value.code == 1


def test_coolify_exits_on_missing_coolify_app_uuid(monkeypatch):
    """--coolify exits 1 when COOLIFY_APP_UUID is absent, before touching browser."""
    monkeypatch.setenv("COOLIFY_URL", "http://coolify:8000")
    monkeypatch.setenv("COOLIFY_TOKEN", "tok")
    monkeypatch.delenv("COOLIFY_APP_UUID", raising=False)
    with pytest.raises(SystemExit) as exc:
        _cmd_export_cookies(["--base64", "--coolify"])
    assert exc.value.code == 1
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python -m pytest tests/unit/test_cli_coolify.py::test_coolify_requires_base64 \
  tests/unit/test_cli_coolify.py::test_restart_requires_coolify \
  tests/unit/test_cli_coolify.py::test_coolify_exits_on_missing_coolify_url \
  tests/unit/test_cli_coolify.py::test_coolify_exits_on_missing_coolify_token \
  tests/unit/test_cli_coolify.py::test_coolify_exits_on_missing_coolify_app_uuid -v
```

Expected: all 5 fail (unrecognised argument `--coolify`).

- [ ] **Step 3: Add `--coolify` and `--restart` flags to the argparse parser**

In `_cmd_export_cookies`, after the existing `--base64` argument definition (around line 80), add:

```python
    parser.add_argument(
        '--coolify',
        action='store_true',
        help='Push FAMILYLINK_COOKIES_B64 to the Coolify app after updating .env. Requires --base64.',
    )
    parser.add_argument(
        '--restart',
        action='store_true',
        help='Restart the Coolify app after pushing the env var. Requires --coolify.',
    )
```

- [ ] **Step 4: Add flag-combination and env-var validation**

Immediately after `args = parser.parse_args(argv)`, before the `if browser_cookie3 is None:` check, insert:

```python
    if args.coolify and not args.base64:
        console.print('[error]--coolify requires --base64[/error]')
        sys.exit(1)
    if args.restart and not args.coolify:
        console.print('[error]--restart requires --coolify[/error]')
        sys.exit(1)

    coolify_url = coolify_token = coolify_app_uuid = None
    if args.coolify:
        coolify_url = os.environ.get('COOLIFY_URL')
        coolify_token = os.environ.get('COOLIFY_TOKEN')
        coolify_app_uuid = os.environ.get('COOLIFY_APP_UUID')
        for name, val in [
            ('COOLIFY_URL', coolify_url),
            ('COOLIFY_TOKEN', coolify_token),
            ('COOLIFY_APP_UUID', coolify_app_uuid),
        ]:
            if not val:
                console.print(f'[error]{name} is not set.[/error]')
                sys.exit(1)
```

- [ ] **Step 5: Call `_push_to_coolify` after the `.env` update**

At the end of the `if args.base64:` block in `_cmd_export_cookies`, after the existing `console.print(f'[success]Updated {env_path}[/success]')` line, add:

```python
        if args.coolify:
            _push_to_coolify(
                encoded,
                coolify_url,
                coolify_token,
                coolify_app_uuid,
                restart=args.restart,
            )
```

- [ ] **Step 6: Run the full test suite**

```bash
python -m pytest tests/unit/test_cli_coolify.py -v
```

Expected: all 12 tests pass.

- [ ] **Step 7: Run linter and formatter**

```bash
ruff check src tests && ruff format src tests
```

Fix any issues.

- [ ] **Step 8: Run the full unit test suite to check for regressions**

```bash
python -m pytest tests/unit/ -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/familylink/cli.py tests/unit/test_cli_coolify.py
git commit -m "feat: add --coolify and --restart flags to export-cookies command"
```
