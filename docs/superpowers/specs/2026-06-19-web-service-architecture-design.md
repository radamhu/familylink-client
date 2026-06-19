# Family Link Web Service — Architecture Design

**Date:** 2026-06-19
**Status:** Approved

## Goal

Transform the existing `familylink` Python CLI/library into a full-stack web service: a FastAPI backend exposing the Google Family Link API, a PostgreSQL database for config, caching, and history, and an HTMX/Jinja2 frontend — deployed on a Heroku-style cloud provider (Railway, Render, Fly.io). Google OAuth protects the web UI.

---

## 1. Repository & Package Structure

Single repo, two source packages under `src/`, one `pyproject.toml`.

```
familylink-client/
├── src/
│   ├── familylink/                   # Pure API client — no web deps
│   │   ├── __init__.py
│   │   ├── auth.py                   # NEW: CookieResolver (extracted from __init__)
│   │   ├── client.py                 # FamilyLink class + missing methods filled in
│   │   ├── models.py                 # Pydantic v2 (drop pydantic.v1 shim)
│   │   └── parsers.py                # NEW: _parse_* methods extracted from client
│   └── familylink_server/            # NEW: Web service
│       ├── __init__.py
│       ├── main.py                   # FastAPI app factory + lifespan
│       ├── config.py                 # Pydantic Settings (reads env vars)
│       ├── auth/
│       │   ├── __init__.py
│       │   └── oauth.py              # Google OAuth 2.0 (authlib) + require_user dep
│       ├── db/
│       │   ├── __init__.py
│       │   ├── models.py             # SQLAlchemy ORM models
│       │   ├── session.py            # Async engine + session factory
│       │   └── migrations/           # Alembic migration scripts
│       ├── routers/
│       │   ├── __init__.py
│       │   ├── apps.py
│       │   ├── devices.py
│       │   ├── members.py
│       │   ├── usage.py
│       │   └── history.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── family_link.py        # Wraps FamilyLink client; cache-aside + audit
│       │   └── usage.py              # Aggregation queries (top 10, daily totals)
│       ├── templates/
│       │   ├── base.html
│       │   ├── dashboard.html
│       │   ├── apps.html
│       │   ├── devices.html
│       │   └── history.html
│       └── static/
│           └── style.css             # Pico.css + minimal overrides
├── pyproject.toml                    # Both packages; server extras separate
├── Procfile                          # web: uvicorn familylink_server.main:app --host 0.0.0.0 --port $PORT
├── alembic.ini
└── ...
```

### Changes to `familylink/` (client package)

| File | Change |
|---|---|
| `auth.py` | New. Extracts the ~130-line cookie/SAPISID resolution from `FamilyLink.__init__` into `CookieResolver` class |
| `client.py` | `__init__` delegates to `CookieResolver`. Add missing methods: `set_app_limit`, `block_app`, `always_allow_app`, `remove_app_limit` |
| `models.py` | Migrate from `pydantic.v1` compat shim to native Pydantic v2. Add typed models for time limit responses (currently returns raw `dict`) |
| `parsers.py` | New. Move all `_parse_*` static methods out of `FamilyLink` class |

---

## 2. Database Design (PostgreSQL + Alembic)

### `app_configs`
Replaces `config.csv`. One row per app rule per child.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `child_id` | TEXT | Google user ID of supervised member |
| `app_name` | TEXT | Display name |
| `package_name` | TEXT | Android package identifier |
| `max_mins` | INTEGER | NULL = no duration limit |
| `days_mask` | TEXT | e.g. `Mon-Fri`, `Sat-Sun`, `` (all days) |
| `time_range` | TEXT | e.g. `09:00-21:00`, `` (all day) |
| `always_allowed` | BOOLEAN | |
| `blocked` | BOOLEAN | |
| `updated_at` | TIMESTAMPTZ | |

### `usage_snapshots`
Written on each API fetch. Enables trend history.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `child_id` | TEXT | |
| `app_package` | TEXT | |
| `date` | DATE | |
| `usage_seconds` | INTEGER | |
| `device_id` | TEXT | |
| `fetched_at` | TIMESTAMPTZ | |

### `device_snapshots`
Caches device lock state so dashboard avoids a live API call on every load.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `device_id` | TEXT UNIQUE | |
| `child_id` | TEXT | |
| `friendly_name` | TEXT | |
| `is_locked` | BOOLEAN | |
| `last_seen` | TIMESTAMPTZ | |

### `audit_log`
Records every write action taken against the Google API.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `child_id` | TEXT | |
| `action` | TEXT | `set_limit`, `block`, `always_allow`, `lock`, `unlock`, `set_downtime` |
| `target` | TEXT | App name or device ID |
| `old_value` | TEXT | JSON-serialised previous state |
| `new_value` | TEXT | JSON-serialised new state |
| `occurred_at` | TIMESTAMPTZ | |

Schema migrations managed by **Alembic** (`alembic revision --autogenerate`).

---

## 3. Authentication

### Web UI — Google OAuth 2.0

- Library: `authlib` + `itsdangerous`
- Flow: `GET /auth/login` → Google consent → `GET /auth/callback` → signed session cookie
- Authorization: only the Google account whose email matches `FAMILYLINK_GOOGLE_EMAIL` may pass; all others receive HTTP 403 after OAuth completes
- Session: signed cookie (`itsdangerous.URLSafeTimedSerializer`); no server-side session storage needed
- FastAPI dependency `require_user` applied to all non-auth routes

### Family Link API — Cookie resolver

- `familylink.auth.CookieResolver` extracted from current `FamilyLink.__init__`
- Cloud deployment path: `FAMILYLINK_COOKIES_B64` only (no browser extraction in containers)
- `FamilyLinkService` instantiates `FamilyLink` once at app startup (lifespan) and holds it as a singleton

### Required environment variables

| Variable | Purpose |
|---|---|
| `FAMILYLINK_COOKIES_B64` | Base64-encoded cookie jar (Family Link API) |
| `FAMILYLINK_GOOGLE_EMAIL` | Google account allowed to log into the web UI |
| `GOOGLE_CLIENT_ID` | OAuth app client ID |
| `GOOGLE_CLIENT_SECRET` | OAuth app client secret |
| `DATABASE_URL` | `postgresql+asyncpg://...` |
| `SECRET_KEY` | Signs session cookies (random 32-byte hex) |

---

## 4. Service Layer

### `FamilyLinkService`

Singleton instantiated at app startup. Responsibilities:
- Calls Google API via `FamilyLink` client
- Cache-aside pattern: checks DB freshness (configurable `CACHE_TTL_SECONDS`, default 900) before hitting the API
- On cache miss: fetches from Google, writes to `usage_snapshots` / `device_snapshots`, returns result
- All write operations (lock, set limit, block): call Google API first, then append to `audit_log`

### `UsageService`

Reads from DB only (no live API calls). Responsibilities:
- Top 10 apps by usage today (aggregated from `usage_snapshots`)
- Daily totals per child over last N days
- Audit log pagination

---

## 5. API Routes

All HTML routes protected by `require_user`. All `POST` routes return HTMX partials.

```
GET  /                           Dashboard page (HTML)
GET  /apps                       App list + current limits (HTML)
POST /apps/{package}/limit       Set time limit → updated row partial
POST /apps/{package}/block       Block app → updated row partial
POST /apps/{package}/allow       Always allow → updated row partial
GET  /devices                    Device list + lock state (HTML)
POST /devices/{id}/lock          Lock device → updated card partial
POST /devices/{id}/unlock        Unlock device → updated card partial
GET  /history                    Usage history + audit log (HTML)
GET  /api/usage/today            JSON — top 10 apps today
GET  /api/members                JSON — child profiles
GET  /auth/login                 Redirect to Google OAuth
GET  /auth/callback              Handle OAuth callback, set session cookie
GET  /auth/logout                Clear session cookie, redirect to /auth/login
```

FastAPI auto-generates OpenAPI schema at `/docs` and `/openapi.json`.

---

## 6. Frontend (Jinja2 + HTMX + Pico.css)

**`base.html`** — shared layout: top nav (Dashboard / Apps / Devices / History), user avatar + logout link, Pico.css CDN link, HTMX CDN link.

**`dashboard.html`**
- Today's total screen time per child
- Top 5 apps by usage today (CSS bar chart, no JS library)
- Device lock state badges with quick lock/unlock buttons
- HTMX auto-refresh every 5 minutes (`hx-trigger="every 5m" hx-get="/" hx-target="main"`)

**`apps.html`**
- Table: app icon · name · state pill (Always allowed / Limited N min / Blocked)
- Inline row edit: click row → HTMX swaps row with mini-form → submit → row updates in place
- Filter tabs: All / Always allowed / Limited / Blocked (HTMX `hx-get` with query param)

**`devices.html`**
- Card per device: model, friendly name, last seen, lock state badge
- Lock/Unlock button per card → HTMX POST → badge + button swap in place

**`history.html`**
- Last 7 days usage stacked by top apps (CSS grid chart)
- Audit log table: timestamp · action · target · old → new value
- Infinite scroll pagination (`hx-trigger="revealed" hx-get="/history?page=N"`)

**CSS**: Pico.css (classless, no build step). No Tailwind, no bundler.

---

## 7. New Dependencies

Added to `pyproject.toml` under `[project.optional-dependencies]` server extras:

```
fastapi>=0.115
uvicorn[standard]>=0.32
authlib>=1.3
itsdangerous>=2.2
sqlalchemy[asyncio]>=2.0
asyncpg>=0.30
alembic>=1.14
jinja2>=3.1
python-multipart>=0.0.12
httpx>=0.28  # already present; also used as ASGI test client
```

---

## 8. What Is NOT Changing

- The `familylink` package public API (`FamilyLink`, `SessionExpiredError`) stays backward-compatible
- The CLI (`familylink config.csv`, `export-cookies`, `fetch-config`) continues to work unchanged
- Cookie auth resolution logic is only moved (to `auth.py`), not rewritten
- The existing `browser_cookie3` optional-extra path is preserved for local use
