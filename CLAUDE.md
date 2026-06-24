# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment setup

- **Python 3.12** via pyenv (`.python-version` pins the version). Virtualenv lives in `.venv/`.
- **direnv** auto-activates `.venv` and exports `PYTHONPATH=src` plus all `.env` vars on `cd`.
- **Do not use `uv`**. Use `pip` and `python -m pytest` directly.

```bash
python -m venv .venv --prompt familylink-client
source .venv/bin/activate
pip install -e ".[dev,test,server]"
direnv allow          # after first-time setup
```

## Commands

```bash
# Tests
python -m pytest                          # all tests
python -m pytest tests/unit/              # unit tests only
python -m pytest tests/server/            # server tests only
python -m pytest tests/unit/test_client.py::test_name -v   # single test

# Lint / format
ruff check src tests                      # lint
ruff check --fix src tests                # lint with auto-fix
ruff format src tests                     # format

# Type check
mypy src

# Server
uvicorn familylink_server.main:app --reload   # dev
alembic upgrade head                          # run DB migrations

# CLI
familylink --dry-run config.csv
familylink export-cookies --base64
```

Pre-commit runs ruff + ruff-format automatically. Install with `pre-commit install`.

## Architecture

There are two Python packages under `src/`:

### `familylink` — API client + CLI

The Google Family Link API returns **positional JSON arrays** (protobuf-over-HTTP), not keyed objects. The flow is:

```
CLI (cli.py)
  └─► FamilyLink client (client.py)  ──httpx──► kidsmanagement-pa.clients6.google.com
        └─► parsers.py  ← converts positional arrays to dicts
              └─► Pydantic models (models.py)  ← validates/types the dicts
```

`parsers.py` is the translation layer between the wire format and the rest of the code. When the API response shape changes, this is where to look.

Authentication is handled by `CookieResolver` in `auth.py`, with this priority (first match wins):
1. `FAMILYLINK_COOKIES_B64` — base64-encoded Netscape cookies.txt (cloud/Docker)
2. `FAMILYLINK_SAPISID` — raw SAPISID only
3. `FAMILYLINK_COOKIE_FILE` / `browser="txt"` — local cookies file
4. Per-profile `sapisid.txt`/`cookies.txt` (when `FAMILYLINK_PROFILES_DIR` is set)
5. `browser_cookie3` — live browser extraction (host only; optional `[browser]` extra)

`browser_cookie3` is intentionally absent in cloud/Docker deployments.

### `familylink_server` — FastAPI web server

```
main.py  ─── lifespan: init_service()
  ├── auth/oauth.py        Google OAuth flow + single-user session cookie (fl_session)
  ├── routers/             One file per page; HTMX POST endpoints return HTML partials
  ├── services/family_link.py   FamilyLinkService singleton: wraps sync client with asyncio.to_thread + TTL cache
  ├── db/models.py         SQLAlchemy ORM (app_configs, usage_snapshots, device_snapshots, audit_log)
  ├── db/session.py        Async engine / session factory
  ├── templates/           Jinja2 HTML (full pages + partials/ for HTMX swaps)
  └── config.py            Settings via pydantic-settings (reads .env)
```

**Service singleton**: `FamilyLinkService` is created once at startup via `lifespan` and injected into routes with `Depends(get_service)`. It holds an in-memory TTL cache (`CACHE_TTL_SECONDS`, default 900 s). Write operations (`set_app_limit`, `block_app`, `always_allow_app`) invalidate the relevant cache entry immediately.

**Auth model**: single-user. Google OAuth login is accepted only when the authenticated email matches `FAMILYLINK_GOOGLE_EMAIL`. The `require_user` dependency (a `Depends` instance defined in `auth/oauth.py`) is used as a default value on route parameters — `_email: str = require_user` — to protect endpoints.

**HTMX pattern**: mutation endpoints (e.g. `POST /apps/{package}/limit`) return a Jinja2 partial (`partials/app_row.html`) that HTMX swaps inline. The full page is rendered only on initial `GET`.

**DB**: async SQLAlchemy + asyncpg. Schema managed by Alembic; migration scripts live in `alembic/versions/`. Run `alembic upgrade head` before starting the server (platforms should set this as a release command).

## Key conventions

- Ruff is configured with Google docstring style (`pydocstyle.convention = "google"`), isort, and single-quoted inline strings.
- `asyncio_mode = "auto"` in pytest — all `async def test_*` functions are awaited automatically.
- Server tests set required env vars in `tests/server/conftest.py` before importing the app.
- The `familylink` package uses `ConfigDict(populate_by_name=True)` on all Pydantic models so both camelCase API aliases and snake_case attribute names work.
