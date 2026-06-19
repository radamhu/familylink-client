# Family Link Server — Web Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Prerequisite:** `docs/superpowers/plans/2026-06-19-client-refactor.md` must be complete before starting this plan.

**Goal:** Build a FastAPI web service (`familylink_server`) that exposes the Google Family Link client as a cloud-hosted web app with a Jinja2+HTMX frontend, PostgreSQL persistence for config/cache/history, and Google OAuth protecting all routes.

**Architecture:** `familylink_server` is a second Python package in `src/` that imports `familylink` as a library. FastAPI handles HTTP; SQLAlchemy async + asyncpg persists to PostgreSQL via Alembic-managed migrations; `FamilyLinkService` (a singleton) wraps the synchronous `FamilyLink` client with `asyncio.to_thread` and a cache-aside layer; Google OAuth (authlib) protects all routes; Jinja2+HTMX renders HTML with Pico.css.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, SQLAlchemy 2.x async, asyncpg, Alembic, authlib, itsdangerous, Jinja2, HTMX, Pico.css (CDN), pytest, httpx

## Global Constraints

- Python ≥ 3.12
- All route handlers must be `async def` — SQLAlchemy uses the async engine throughout
- `FamilyLink` client is synchronous (`httpx.Client`) — always call it via `asyncio.to_thread()`
- `DATABASE_URL` must use `postgresql+asyncpg://` scheme
- All routes (except `/auth/*`) protected by `require_user` dependency
- Only the Google account matching `FAMILYLINK_GOOGLE_EMAIL` env var may authenticate
- No bundler, no npm — frontend is Jinja2 + HTMX CDN + Pico.css CDN only
- TDD: write the failing test before implementation
- One commit per task minimum

---

### Task 1: Package scaffold + pyproject.toml update

**Files:**
- Modify: `pyproject.toml`
- Create: `src/familylink_server/__init__.py`
- Create: `src/familylink_server/config.py`
- Create: `Procfile`
- Create: `tests/server/__init__.py`
- Create: `tests/server/conftest.py`

**Interfaces:**
- Produces: `from familylink_server.config import settings` — a Pydantic Settings object with all required env vars

- [ ] **Step 1: Write failing test for config**

```python
# tests/server/test_config.py
import os
import pytest


def test_settings_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost/test")
    monkeypatch.setenv("SECRET_KEY", "test-secret-32-chars-exactly!!!!")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("FAMILYLINK_GOOGLE_EMAIL", "parent@gmail.com")
    monkeypatch.setenv("FAMILYLINK_COOKIES_B64", "dGVzdA==")

    from familylink_server.config import Settings
    s = Settings()
    assert s.database_url == "postgresql+asyncpg://localhost/test"
    assert s.google_client_id == "client-id"
    assert s.familylink_google_email == "parent@gmail.com"
    assert s.cache_ttl_seconds == 900  # default
```

- [ ] **Step 2: Run test — confirm it fails**

```bash
pytest tests/server/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'familylink_server'`

- [ ] **Step 3: Update pyproject.toml**

Add `familylink_server` to packages, add server dependencies, and add test config:

```toml
[project]
name = "familylink"
version = "0.2.0"
# ... existing fields ...
dependencies = [
    "httpx>=0.28.1",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "rich>=13.7.0",
]

[project.optional-dependencies]
browser = [
    "browser-cookie3>=0.19.1",
]
server = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "authlib>=1.3",
    "itsdangerous>=2.2",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "jinja2>=3.1",
    "python-multipart>=0.0.12",
]
dev = [
    "pre-commit>=4.0.1",
    "ruff>=0.8.4",
]
test = [
    "pytest>=8.0.0",
    "pytest-cov>=5.0.0",
    "pytest-mock>=3.12.0",
    "pytest-httpx>=0.30.0",
    "pytest-asyncio>=0.23.0",
    "freezegun>=1.5.0",
    "mypy>=1.8.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/familylink", "src/familylink_server"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 4: Create package files**

Create `src/familylink_server/__init__.py` (empty):

```python
```

Create `src/familylink_server/config.py`:

```python
"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    google_client_id: str
    google_client_secret: str
    familylink_google_email: str
    familylink_cookies_b64: str = ""
    familylink_cookie_file: str = ""
    familylink_sapisid: str = ""
    cache_ttl_seconds: int = 900

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

Create `tests/server/__init__.py` (empty).

Create `tests/server/conftest.py`:

```python
"""Shared fixtures for server tests."""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/familylink_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-bytes-exactly!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("FAMILYLINK_GOOGLE_EMAIL", "parent@gmail.com")
os.environ.setdefault("FAMILYLINK_COOKIES_B64", "dGVzdA==")
```

Create `Procfile`:

```
web: uvicorn familylink_server.main:app --host 0.0.0.0 --port $PORT
```

- [ ] **Step 5: Install server deps and run test**

```bash
pip install -e ".[server,test]"
pytest tests/server/test_config.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/familylink_server/ tests/server/ Procfile
git commit -m "feat: scaffold familylink_server package with config"
```

---

### Task 2: Database models (SQLAlchemy async)

**Files:**
- Create: `src/familylink_server/db/__init__.py`
- Create: `src/familylink_server/db/models.py`
- Create: `src/familylink_server/db/session.py`
- Create: `tests/server/test_db_models.py`

**Interfaces:**
- Produces:
  - `get_session()` — async context manager yielding `AsyncSession`
  - ORM classes: `AppConfig`, `UsageSnapshot`, `DeviceSnapshot`, `AuditLog`
  - All importable from `familylink_server.db`

- [ ] **Step 1: Write failing tests**

```python
# tests/server/test_db_models.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from familylink_server.db.models import Base, AppConfig, UsageSnapshot, DeviceSnapshot, AuditLog
from datetime import date, datetime, timezone


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def test_app_config_insert_and_read(db_session):
    config = AppConfig(
        child_id="child1",
        app_name="YouTube",
        package_name="com.google.android.youtube",
        max_mins=30,
        days_mask="Mon-Fri",
        time_range="09:00-21:00",
        always_allowed=False,
        blocked=False,
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)
    assert config.id is not None
    assert config.app_name == "YouTube"


async def test_usage_snapshot_insert(db_session):
    snap = UsageSnapshot(
        child_id="child1",
        app_package="com.google.android.youtube",
        date=date.today(),
        usage_seconds=1800,
        device_id="dev1",
        fetched_at=datetime.now(timezone.utc),
    )
    db_session.add(snap)
    await db_session.commit()
    assert snap.id is not None


async def test_device_snapshot_unique_device_id(db_session):
    snap = DeviceSnapshot(
        device_id="dev1",
        child_id="child1",
        friendly_name="Pixel 7",
        is_locked=False,
        last_seen=datetime.now(timezone.utc),
    )
    db_session.add(snap)
    await db_session.commit()
    assert snap.id is not None


async def test_audit_log_insert(db_session):
    log = AuditLog(
        child_id="child1",
        action="set_limit",
        target="com.google.android.youtube",
        old_value="60",
        new_value="30",
        occurred_at=datetime.now(timezone.utc),
    )
    db_session.add(log)
    await db_session.commit()
    assert log.id is not None
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pip install aiosqlite  # for in-memory SQLite in tests
pytest tests/server/test_db_models.py -v
```

Expected: `ImportError: cannot import name 'Base' from 'familylink_server.db.models'`

- [ ] **Step 3: Create db/models.py**

```python
# src/familylink_server/db/models.py
"""SQLAlchemy ORM models."""

from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AppConfig(Base):
    __tablename__ = "app_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_name: Mapped[str] = mapped_column(String(256), nullable=False)
    package_name: Mapped[str] = mapped_column(String(256), nullable=False)
    max_mins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_mask: Mapped[str] = mapped_column(String(64), default="")
    time_range: Mapped[str] = mapped_column(String(32), default="")
    always_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UsageSnapshot(Base):
    __tablename__ = "usage_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_package: Mapped[str] = mapped_column(String(256), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    usage_seconds: Mapped[int] = mapped_column(Integer, default=0)
    device_id: Mapped[str] = mapped_column(String(128), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeviceSnapshot(Base):
    __tablename__ = "device_snapshots"
    __table_args__ = (UniqueConstraint("device_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False)
    friendly_name: Mapped[str] = mapped_column(String(256), default="")
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(256), default="")
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

Create `src/familylink_server/db/__init__.py`:

```python
from familylink_server.db.models import AppConfig, AuditLog, Base, DeviceSnapshot, UsageSnapshot
from familylink_server.db.session import get_session

__all__ = ["AppConfig", "AuditLog", "Base", "DeviceSnapshot", "UsageSnapshot", "get_session"]
```

Create `src/familylink_server/db/session.py`:

```python
"""Async SQLAlchemy session factory."""

from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from familylink_server.config import settings

_engine = create_async_engine(settings.database_url, echo=False)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _session_factory() as session:
        yield session
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
pytest tests/server/test_db_models.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/db/ tests/server/test_db_models.py
git commit -m "feat: add SQLAlchemy async ORM models (AppConfig, UsageSnapshot, DeviceSnapshot, AuditLog)"
```

---

### Task 3: Alembic setup + initial migration

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/` (directory, first migration generated here)

**Interfaces:**
- Produces: `alembic upgrade head` creates all four tables in the target database

- [ ] **Step 1: Initialise Alembic**

```bash
alembic init alembic
```

This creates `alembic.ini` and `alembic/` directory. Then edit both files:

- [ ] **Step 2: Configure alembic.ini**

In `alembic.ini`, set:

```ini
script_location = alembic
# Leave sqlalchemy.url blank — we read it from env in env.py
sqlalchemy.url =
```

- [ ] **Step 3: Configure alembic/env.py**

Replace the generated `alembic/env.py` with:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from familylink_server.config import settings
from familylink_server.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(settings.database_url)
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda sync_conn: context.configure(
                connection=sync_conn, target_metadata=target_metadata
            )
        )
        async with connection.begin():
            await connection.run_sync(lambda _: context.run_migrations())
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Generate initial migration**

```bash
alembic revision --autogenerate -m "initial schema"
```

Inspect the generated file in `alembic/versions/` — verify it creates all four tables (`app_configs`, `usage_snapshots`, `device_snapshots`, `audit_log`).

- [ ] **Step 5: Apply migration to a test database**

```bash
# Requires a running Postgres — use Docker if needed:
docker run -d --name fl-pg -e POSTGRES_PASSWORD=pass -e POSTGRES_DB=familylink -p 5432:5432 postgres:16
export DATABASE_URL=postgresql+asyncpg://postgres:pass@localhost/familylink
alembic upgrade head
```

Expected output ends with: `INFO  [alembic.runtime.migration] Running upgrade -> <hash>, initial schema`

- [ ] **Step 6: Commit**

```bash
git add alembic.ini alembic/
git commit -m "feat: add Alembic migration setup and initial schema migration"
```

---

### Task 4: Google OAuth (auth routes + require_user dependency)

**Files:**
- Create: `src/familylink_server/auth/__init__.py`
- Create: `src/familylink_server/auth/oauth.py`
- Create: `tests/server/test_auth.py`

**Interfaces:**
- Produces:
  - `router` — FastAPI `APIRouter` with `GET /auth/login`, `GET /auth/callback`, `GET /auth/logout`
  - `require_user` — FastAPI dependency that extracts the signed session cookie and returns the user email string; raises `HTTPException(401)` if missing or invalid
  - Session cookie name: `fl_session`; payload: `{"email": "parent@gmail.com"}`

- [ ] **Step 1: Write failing tests**

```python
# tests/server/test_auth.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer

from familylink_server.auth.oauth import require_user, router as auth_router
from familylink_server.config import settings


@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(auth_router)

    @application.get("/protected")
    async def protected(email: str = require_user):  # type: ignore[assignment]
        return {"email": email}

    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=True)


def _make_session_cookie(email: str) -> str:
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": email})


def test_protected_route_rejects_no_cookie(client):
    resp = client.get("/protected")
    assert resp.status_code == 401


def test_protected_route_accepts_valid_cookie(client):
    cookie = _make_session_cookie(settings.familylink_google_email)
    resp = client.get("/protected", cookies={"fl_session": cookie})
    assert resp.status_code == 200
    assert resp.json()["email"] == settings.familylink_google_email


def test_protected_route_rejects_wrong_email(client):
    cookie = _make_session_cookie("intruder@gmail.com")
    resp = client.get("/protected", cookies={"fl_session": cookie})
    assert resp.status_code == 403


def test_auth_login_redirects_to_google(client):
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "accounts.google.com" in resp.headers.get("location", "")


def test_auth_logout_clears_cookie(client):
    cookie = _make_session_cookie(settings.familylink_google_email)
    resp = client.get("/auth/logout", cookies={"fl_session": cookie}, follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.cookies.get("fl_session") == "" or "fl_session" not in resp.cookies
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/server/test_auth.py -v
```

Expected: `ImportError: cannot import name 'require_user' from 'familylink_server.auth.oauth'`

- [ ] **Step 3: Create auth/oauth.py**

```python
# src/familylink_server/auth/oauth.py
"""Google OAuth 2.0 login flow and session cookie dependency."""

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Cookie, HTTPException, Request
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


async def require_user(fl_session: str | None = Cookie(default=None, alias=_COOKIE_NAME)) -> str:
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


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    redirect_uri = str(request.url_for("auth_callback"))
    return await _oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(request: Request) -> RedirectResponse:
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
    response = RedirectResponse(url="/auth/login")
    response.delete_cookie(_COOKIE_NAME)
    return response
```

Create `src/familylink_server/auth/__init__.py` (empty).

- [ ] **Step 4: Run tests — confirm they pass**

```bash
pytest tests/server/test_auth.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/auth/ tests/server/test_auth.py
git commit -m "feat: add Google OAuth login flow and require_user session dependency"
```

---

### Task 5: FamilyLinkService (singleton + cache-aside)

**Files:**
- Create: `src/familylink_server/services/__init__.py`
- Create: `src/familylink_server/services/family_link.py`
- Create: `tests/server/test_family_link_service.py`

**Interfaces:**
- Produces:
  - `FamilyLinkService` — instantiated once at app startup, injected via FastAPI dependency
  - `async get_members() -> MembersResponse`
  - `async get_apps_and_usage(child_id: str) -> AppUsage`
  - `async lock_device(device_id: str, child_id: str | None) -> None`
  - `async unlock_device(device_id: str, child_id: str | None) -> None`
  - `async set_app_limit(package_name: str, minutes: int, child_id: str | None) -> None`
  - `async block_app(package_name: str, child_id: str | None) -> None`
  - `async always_allow_app(package_name: str, child_id: str | None) -> None`
  - `get_service()` — FastAPI dependency returning the singleton

- [ ] **Step 1: Write failing tests**

```python
# tests/server/test_family_link_service.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from familylink_server.services.family_link import FamilyLinkService


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_members.return_value = MagicMock(members=[])
    client.get_apps_and_usage.return_value = MagicMock(apps=[], device_info=[], app_usage_sessions=[])
    client.lock_device.return_value = {}
    client.unlock_device.return_value = {}
    return client


@pytest.fixture
def service(mock_client):
    svc = FamilyLinkService.__new__(FamilyLinkService)
    svc._client = mock_client
    svc._ttl = 0  # disable caching for tests
    return svc


async def test_get_members_delegates_to_client(service, mock_client):
    result = await service.get_members()
    mock_client.get_members.assert_called_once()
    assert result.members == []


async def test_get_apps_and_usage_delegates_to_client(service, mock_client):
    result = await service.get_apps_and_usage("child1")
    mock_client.get_apps_and_usage.assert_called_once_with("child1")


async def test_lock_device_delegates_to_client(service, mock_client):
    await service.lock_device("dev1", child_id="child1")
    mock_client.lock_device.assert_called_once_with(device_id="dev1", account_id="child1")


async def test_unlock_device_delegates_to_client(service, mock_client):
    await service.unlock_device("dev1", child_id="child1")
    mock_client.unlock_device.assert_called_once_with(device_id="dev1", account_id="child1")
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/server/test_family_link_service.py -v
```

Expected: `ImportError: cannot import name 'FamilyLinkService'`

- [ ] **Step 3: Create services/family_link.py**

```python
# src/familylink_server/services/family_link.py
"""Singleton service wrapping the FamilyLink client with async + cache-aside."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from familylink import FamilyLink
from familylink.models import AppUsage, MembersResponse
from familylink_server.config import settings

logger = logging.getLogger(__name__)


class FamilyLinkService:
    """Wraps the synchronous FamilyLink client for async FastAPI use."""

    def __init__(self) -> None:
        self._client = FamilyLink()
        self._ttl = settings.cache_ttl_seconds
        self._members_cache: tuple[MembersResponse, datetime] | None = None
        self._usage_cache: dict[str, tuple[AppUsage, datetime]] = {}

    def _is_fresh(self, ts: datetime) -> bool:
        return (datetime.now(timezone.utc) - ts).total_seconds() < self._ttl

    async def get_members(self) -> MembersResponse:
        if self._members_cache and self._is_fresh(self._members_cache[1]):
            return self._members_cache[0]
        result = await asyncio.to_thread(self._client.get_members)
        self._members_cache = (result, datetime.now(timezone.utc))
        return result

    async def get_apps_and_usage(self, child_id: str) -> AppUsage:
        cached = self._usage_cache.get(child_id)
        if cached and self._is_fresh(cached[1]):
            return cached[0]
        result = await asyncio.to_thread(self._client.get_apps_and_usage, child_id)
        self._usage_cache[child_id] = (result, datetime.now(timezone.utc))
        return result

    async def lock_device(self, device_id: str, child_id: str | None = None) -> None:
        await asyncio.to_thread(self._client.lock_device, account_id=child_id, device_id=device_id)

    async def unlock_device(self, device_id: str, child_id: str | None = None) -> None:
        await asyncio.to_thread(self._client.unlock_device, account_id=child_id, device_id=device_id)

    async def set_app_limit(self, package_name: str, minutes: int, child_id: str | None = None) -> None:
        await asyncio.to_thread(self._client.set_app_limit, package_name, minutes, child_id)
        self._usage_cache.pop(child_id or "", None)

    async def block_app(self, package_name: str, child_id: str | None = None) -> None:
        await asyncio.to_thread(self._client.block_app, package_name, child_id)
        self._usage_cache.pop(child_id or "", None)

    async def always_allow_app(self, package_name: str, child_id: str | None = None) -> None:
        await asyncio.to_thread(self._client.always_allow_app, package_name, child_id)
        self._usage_cache.pop(child_id or "", None)


_service: FamilyLinkService | None = None


def init_service() -> FamilyLinkService:
    """Called once at app startup (lifespan). Returns the singleton."""
    global _service
    _service = FamilyLinkService()
    return _service


def get_service() -> FamilyLinkService:
    """FastAPI dependency — returns the singleton."""
    if _service is None:
        raise RuntimeError("FamilyLinkService not initialised — call init_service() in lifespan")
    return _service
```

Create `src/familylink_server/services/__init__.py` (empty).

- [ ] **Step 4: Run tests — confirm they pass**

```bash
pytest tests/server/test_family_link_service.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/services/ tests/server/test_family_link_service.py
git commit -m "feat: add FamilyLinkService singleton with async wrapper and cache-aside"
```

---

### Task 6: FastAPI app factory + lifespan

**Files:**
- Create: `src/familylink_server/main.py`
- Create: `tests/server/test_main.py`

**Interfaces:**
- Produces: `app` — FastAPI application, importable as `familylink_server.main:app`
- Consumes:
  - `init_service()` from `familylink_server.services.family_link`
  - `router` from `familylink_server.auth.oauth`

- [ ] **Step 1: Write failing tests**

```python
# tests/server/test_main.py
from fastapi.testclient import TestClient
import pytest


def test_docs_endpoint_exists():
    from familylink_server.main import app
    client = TestClient(app)
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_openapi_json_exists():
    from familylink_server.main import app
    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert "familylink" in resp.json()["info"]["title"].lower()


def test_auth_login_route_exists():
    from familylink_server.main import app
    client = TestClient(app)
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/server/test_main.py -v
```

Expected: `ImportError: cannot import name 'app' from 'familylink_server.main'`

- [ ] **Step 3: Create main.py**

```python
# src/familylink_server/main.py
"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from familylink_server.auth.oauth import router as auth_router
from familylink_server.services.family_link import init_service


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    init_service()
    yield


app = FastAPI(
    title="Family Link",
    description="Google Family Link management web service",
    lifespan=lifespan,
)

app.include_router(auth_router)

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")
```

Create `src/familylink_server/static/` directory with a placeholder:

```bash
mkdir -p src/familylink_server/static
touch src/familylink_server/static/.gitkeep
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
pytest tests/server/test_main.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/main.py src/familylink_server/static/ tests/server/test_main.py
git commit -m "feat: add FastAPI app factory with lifespan and auth router"
```

---

### Task 7: Members + Usage JSON routers

**Files:**
- Create: `src/familylink_server/routers/__init__.py`
- Create: `src/familylink_server/routers/members.py`
- Create: `src/familylink_server/routers/usage.py`
- Modify: `src/familylink_server/main.py`
- Create: `tests/server/test_routers_members.py`

**Interfaces:**
- Produces:
  - `GET /api/members` → JSON list of child members
  - `GET /api/usage/today` → JSON top-10 apps by seconds today

- [ ] **Step 1: Write failing tests**

```python
# tests/server/test_routers_members.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from itsdangerous import URLSafeSerializer
from familylink_server.config import settings


def _session_cookie():
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": settings.familylink_google_email})


@pytest.fixture
def client():
    # Patch FamilyLinkService init so no real Google auth needed
    mock_svc = MagicMock()
    mock_svc.get_members = MagicMock(return_value=MagicMock(members=[
        MagicMock(
            user_id="child1",
            profile=MagicMock(display_name="Alice", email="alice@example.com"),
            member_supervision_info=MagicMock(is_supervised_member=True),
        )
    ]))

    with patch("familylink_server.services.family_link.init_service", return_value=mock_svc), \
         patch("familylink_server.services.family_link._service", mock_svc):
        from familylink_server.main import app
        return TestClient(app)


def test_get_members_returns_200(client):
    resp = client.get("/api/members", cookies={"fl_session": _session_cookie()})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_get_members_rejects_no_session(client):
    resp = client.get("/api/members")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/server/test_routers_members.py -v
```

Expected: `404 Not Found` for `/api/members`

- [ ] **Step 3: Create routers/members.py**

```python
# src/familylink_server/routers/members.py
from fastapi import APIRouter, Depends
from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/members")
async def get_members(
    _email: str = Depends(require_user),
    svc: FamilyLinkService = Depends(get_service),
) -> list[dict]:
    result = await svc.get_members()
    return [
        {
            "user_id": m.user_id,
            "display_name": m.profile.display_name,
            "email": m.profile.email,
            "is_supervised": bool(
                m.member_supervision_info and m.member_supervision_info.is_supervised_member
            ),
        }
        for m in result.members
    ]
```

Create `src/familylink_server/routers/usage.py`:

```python
# src/familylink_server/routers/usage.py
from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import UsageSnapshot, get_session

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/usage/today")
async def get_usage_today(
    _email: str = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    today = date.today()
    q = (
        select(UsageSnapshot.app_package, func.sum(UsageSnapshot.usage_seconds).label("total"))
        .where(UsageSnapshot.date == today)
        .group_by(UsageSnapshot.app_package)
        .order_by(func.sum(UsageSnapshot.usage_seconds).desc())
        .limit(10)
    )
    rows = (await session.execute(q)).all()
    return [{"package": r.app_package, "seconds": r.total} for r in rows]
```

Create `src/familylink_server/routers/__init__.py` (empty).

Register routers in `main.py` — add after existing `include_router` call:

```python
from familylink_server.routers.members import router as members_router
from familylink_server.routers.usage import router as usage_router

app.include_router(members_router)
app.include_router(usage_router)
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
pytest tests/server/test_routers_members.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/routers/ src/familylink_server/main.py tests/server/test_routers_members.py
git commit -m "feat: add /api/members and /api/usage/today JSON routers"
```

---

### Task 8: Devices router + template

**Files:**
- Create: `src/familylink_server/routers/devices.py`
- Create: `src/familylink_server/templates/devices.html`
- Modify: `src/familylink_server/main.py` (register router + Jinja2)
- Create: `tests/server/test_routers_devices.py`

**Interfaces:**
- Produces:
  - `GET /devices` → HTML page listing devices with lock state
  - `POST /devices/{device_id}/lock` → HTMX partial (updated card)
  - `POST /devices/{device_id}/unlock` → HTMX partial (updated card)

- [ ] **Step 1: Write failing tests**

```python
# tests/server/test_routers_devices.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
from itsdangerous import URLSafeSerializer
from familylink_server.config import settings


def _cookie():
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": settings.familylink_google_email})


def _make_client(mock_svc):
    with patch("familylink_server.services.family_link._service", mock_svc):
        from familylink_server.main import app
        return TestClient(app)


def test_devices_page_returns_200():
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[
        MagicMock(user_id="child1", member_supervision_info=MagicMock(is_supervised_member=True))
    ]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=MagicMock(
        device_info=[MagicMock(device_id="dev1", display_info=MagicMock(friendly_name="Pixel 7"))],
    ))
    client = _make_client(mock_svc)
    resp = client.get("/devices", cookies={"fl_session": _cookie()})
    assert resp.status_code == 200
    assert "Pixel 7" in resp.text


def test_lock_device_returns_partial_html():
    mock_svc = MagicMock()
    mock_svc.lock_device = AsyncMock(return_value=None)
    client = _make_client(mock_svc)
    resp = client.post(
        "/devices/dev1/lock",
        data={"child_id": "child1"},
        cookies={"fl_session": _cookie()},
    )
    assert resp.status_code == 200
    assert "locked" in resp.text.lower()
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/server/test_routers_devices.py -v
```

Expected: `404 Not Found`

- [ ] **Step 3: Create Jinja2 setup in main.py**

Add to `main.py`:

```python
from pathlib import Path
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
```

Create `src/familylink_server/templates/` directory.

- [ ] **Step 4: Create routers/devices.py**

```python
# src/familylink_server/routers/devices.py
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=["devices"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/devices", response_class=HTMLResponse)
async def devices_page(
    request: Request,
    _email: str = Depends(require_user),
    svc: FamilyLinkService = Depends(get_service),
) -> HTMLResponse:
    members = await svc.get_members()
    children = [
        m for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    devices = []
    for child in children:
        usage = await svc.get_apps_and_usage(child.user_id)
        for d in usage.device_info:
            devices.append({
                "device_id": d.device_id,
                "child_id": child.user_id,
                "friendly_name": d.display_info.friendly_name,
                "model": d.display_info.model,
                "is_locked": False,
            })
    return templates.TemplateResponse(
        "devices.html", {"request": request, "devices": devices}
    )


@router.post("/devices/{device_id}/lock", response_class=HTMLResponse)
async def lock_device(
    device_id: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = Depends(require_user),
    svc: FamilyLinkService = Depends(get_service),
) -> HTMLResponse:
    await svc.lock_device(device_id, child_id=child_id)
    return templates.TemplateResponse(
        "partials/device_card.html",
        {"request": request, "device": {"device_id": device_id, "child_id": child_id, "is_locked": True}},
    )


@router.post("/devices/{device_id}/unlock", response_class=HTMLResponse)
async def unlock_device(
    device_id: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = Depends(require_user),
    svc: FamilyLinkService = Depends(get_service),
) -> HTMLResponse:
    await svc.unlock_device(device_id, child_id=child_id)
    return templates.TemplateResponse(
        "partials/device_card.html",
        {"request": request, "device": {"device_id": device_id, "child_id": child_id, "is_locked": False}},
    )
```

- [ ] **Step 5: Create templates**

Create `src/familylink_server/templates/partials/` directory.

Create `src/familylink_server/templates/partials/device_card.html`:

```html
<div id="device-{{ device.device_id }}" class="card">
  <header>
    <strong>{{ device.friendly_name or device.device_id }}</strong>
    {% if device.is_locked %}
      <span class="badge" style="color:var(--pico-color-red-500)">locked</span>
    {% else %}
      <span class="badge" style="color:var(--pico-color-green-500)">unlocked</span>
    {% endif %}
  </header>
  <footer>
    {% if device.is_locked %}
      <form hx-post="/devices/{{ device.device_id }}/unlock"
            hx-target="#device-{{ device.device_id }}"
            hx-swap="outerHTML">
        <input type="hidden" name="child_id" value="{{ device.child_id }}">
        <button type="submit">Unlock</button>
      </form>
    {% else %}
      <form hx-post="/devices/{{ device.device_id }}/lock"
            hx-target="#device-{{ device.device_id }}"
            hx-swap="outerHTML">
        <input type="hidden" name="child_id" value="{{ device.child_id }}">
        <button type="submit" class="secondary">Lock</button>
      </form>
    {% endif %}
  </footer>
</div>
```

Create `src/familylink_server/templates/devices.html`:

```html
{% extends "base.html" %}
{% block title %}Devices{% endblock %}
{% block content %}
<h2>Devices</h2>
<div class="grid">
  {% for device in devices %}
    {% include "partials/device_card.html" %}
  {% endfor %}
  {% if not devices %}
    <p>No devices found.</p>
  {% endif %}
</div>
{% endblock %}
```

Register router in `main.py`:

```python
from familylink_server.routers.devices import router as devices_router
app.include_router(devices_router)
```

- [ ] **Step 6: Run tests — confirm they pass**

```bash
pytest tests/server/test_routers_devices.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/familylink_server/routers/devices.py src/familylink_server/templates/ tests/server/test_routers_devices.py
git commit -m "feat: add /devices page and lock/unlock HTMX endpoints"
```

---

### Task 9: Apps router + template

**Files:**
- Create: `src/familylink_server/routers/apps.py`
- Create: `src/familylink_server/templates/apps.html`
- Create: `src/familylink_server/templates/partials/app_row.html`
- Modify: `src/familylink_server/main.py`
- Create: `tests/server/test_routers_apps.py`

**Interfaces:**
- Produces:
  - `GET /apps` → HTML table of apps with current supervision state
  - `POST /apps/{package}/limit` → HTMX partial (updated row)
  - `POST /apps/{package}/block` → HTMX partial (updated row)
  - `POST /apps/{package}/allow` → HTMX partial (updated row)

- [ ] **Step 1: Write failing tests**

```python
# tests/server/test_routers_apps.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
from itsdangerous import URLSafeSerializer
from familylink_server.config import settings


def _cookie():
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": settings.familylink_google_email})


def _make_app_mock(title, package, hidden=False, limit_mins=None, always_allowed=False):
    app_mock = MagicMock()
    app_mock.title = title
    app_mock.package_name = package
    app_mock.supervision_setting.hidden = hidden
    app_mock.supervision_setting.usage_limit = (
        MagicMock(daily_usage_limit_mins=limit_mins, enabled=True) if limit_mins else None
    )
    app_mock.supervision_setting.always_allowed_app_info = (
        MagicMock(always_allowed_state="alwaysAllowedStateEnabled") if always_allowed else None
    )
    return app_mock


def _make_client(mock_svc):
    with patch("familylink_server.services.family_link._service", mock_svc):
        from familylink_server.main import app
        return TestClient(app)


def test_apps_page_returns_200():
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[
        MagicMock(user_id="child1", member_supervision_info=MagicMock(is_supervised_member=True))
    ]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=MagicMock(
        apps=[_make_app_mock("YouTube", "com.google.android.youtube", limit_mins=30)],
        device_info=[], app_usage_sessions=[],
    ))
    client = _make_client(mock_svc)
    resp = client.get("/apps", cookies={"fl_session": _cookie()})
    assert resp.status_code == 200
    assert "YouTube" in resp.text


def test_set_limit_returns_partial(monkeypatch):
    mock_svc = MagicMock()
    mock_svc.set_app_limit = AsyncMock(return_value=None)
    client = _make_client(mock_svc)
    resp = client.post(
        "/apps/com.google.android.youtube/limit",
        data={"child_id": "child1", "minutes": "45"},
        cookies={"fl_session": _cookie()},
    )
    assert resp.status_code == 200
    mock_svc.set_app_limit.assert_called_once_with(
        "com.google.android.youtube", 45, child_id="child1"
    )


def test_block_app_returns_partial():
    mock_svc = MagicMock()
    mock_svc.block_app = AsyncMock(return_value=None)
    client = _make_client(mock_svc)
    resp = client.post(
        "/apps/com.google.android.youtube/block",
        data={"child_id": "child1"},
        cookies={"fl_session": _cookie()},
    )
    assert resp.status_code == 200
    mock_svc.block_app.assert_called_once_with("com.google.android.youtube", child_id="child1")
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/server/test_routers_apps.py -v
```

Expected: `404 Not Found` for `/apps`

- [ ] **Step 3: Create routers/apps.py**

```python
# src/familylink_server/routers/apps.py
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=["apps"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _app_state(app) -> dict:
    sup = app.supervision_setting
    if sup.hidden:
        state, state_label = "blocked", "Blocked"
    elif sup.usage_limit:
        state, state_label = "limited", f"Limited {sup.usage_limit.daily_usage_limit_mins} min"
    elif sup.always_allowed_app_info:
        state, state_label = "allowed", "Always allowed"
    else:
        state, state_label = "unmanaged", "Unmanaged"
    return {
        "package_name": app.package_name,
        "title": app.title,
        "state": state,
        "state_label": state_label,
        "limit_mins": sup.usage_limit.daily_usage_limit_mins if sup.usage_limit else None,
    }


@router.get("/apps", response_class=HTMLResponse)
async def apps_page(
    request: Request,
    filter: str = "all",
    _email: str = Depends(require_user),
    svc: FamilyLinkService = Depends(get_service),
) -> HTMLResponse:
    members = await svc.get_members()
    children = [
        m for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    child = children[0] if children else None
    apps = []
    if child:
        usage = await svc.get_apps_and_usage(child.user_id)
        apps = [
            dict(_app_state(a), child_id=child.user_id)
            for a in sorted(usage.apps, key=lambda x: x.title.lower())
        ]
        if filter != "all":
            apps = [a for a in apps if a["state"] == filter]
    return templates.TemplateResponse(
        "apps.html",
        {"request": request, "apps": apps, "child_id": child.user_id if child else "", "filter": filter},
    )


@router.post("/apps/{package}/limit", response_class=HTMLResponse)
async def set_limit(
    package: str,
    request: Request,
    child_id: str = Form(...),
    minutes: int = Form(...),
    _email: str = Depends(require_user),
    svc: FamilyLinkService = Depends(get_service),
) -> HTMLResponse:
    await svc.set_app_limit(package, minutes, child_id=child_id)
    app_data = {
        "package_name": package, "title": package, "state": "limited",
        "state_label": f"Limited {minutes} min", "limit_mins": minutes, "child_id": child_id,
    }
    return templates.TemplateResponse(
        "partials/app_row.html", {"request": request, "app": app_data}
    )


@router.post("/apps/{package}/block", response_class=HTMLResponse)
async def block_app(
    package: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = Depends(require_user),
    svc: FamilyLinkService = Depends(get_service),
) -> HTMLResponse:
    await svc.block_app(package, child_id=child_id)
    app_data = {
        "package_name": package, "title": package,
        "state": "blocked", "state_label": "Blocked", "limit_mins": None, "child_id": child_id,
    }
    return templates.TemplateResponse(
        "partials/app_row.html", {"request": request, "app": app_data}
    )


@router.post("/apps/{package}/allow", response_class=HTMLResponse)
async def allow_app(
    package: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = Depends(require_user),
    svc: FamilyLinkService = Depends(get_service),
) -> HTMLResponse:
    await svc.always_allow_app(package, child_id=child_id)
    app_data = {
        "package_name": package, "title": package,
        "state": "allowed", "state_label": "Always allowed", "limit_mins": None, "child_id": child_id,
    }
    return templates.TemplateResponse(
        "partials/app_row.html", {"request": request, "app": app_data}
    )
```

Create `src/familylink_server/templates/partials/app_row.html`:

```html
<tr id="row-{{ app.package_name | replace('.', '-') }}">
  <td>{{ app.title }}</td>
  <td>
    {% if app.state == "blocked" %}
      <span style="color:var(--pico-color-red-500)">Blocked</span>
    {% elif app.state == "limited" %}
      <span style="color:var(--pico-color-orange-500)">{{ app.state_label }}</span>
    {% elif app.state == "allowed" %}
      <span style="color:var(--pico-color-green-500)">Always allowed</span>
    {% else %}
      <span style="color:var(--pico-color-grey-500)">Unmanaged</span>
    {% endif %}
  </td>
  <td>
    <details>
      <summary role="button" class="outline secondary" style="font-size:0.8rem">Edit</summary>
      <div style="padding:0.5rem 0">
        <form hx-post="/apps/{{ app.package_name }}/allow"
              hx-target="#row-{{ app.package_name | replace('.', '-') }}"
              hx-swap="outerHTML" style="display:inline">
          <input type="hidden" name="child_id" value="{{ app.child_id }}">
          <button type="submit" class="outline" style="font-size:0.75rem;padding:0.25rem 0.5rem">Always allow</button>
        </form>
        <form hx-post="/apps/{{ app.package_name }}/block"
              hx-target="#row-{{ app.package_name | replace('.', '-') }}"
              hx-swap="outerHTML" style="display:inline">
          <input type="hidden" name="child_id" value="{{ app.child_id }}">
          <button type="submit" class="outline secondary" style="font-size:0.75rem;padding:0.25rem 0.5rem">Block</button>
        </form>
        <form hx-post="/apps/{{ app.package_name }}/limit"
              hx-target="#row-{{ app.package_name | replace('.', '-') }}"
              hx-swap="outerHTML" style="display:inline">
          <input type="hidden" name="child_id" value="{{ app.child_id }}">
          <input type="number" name="minutes" value="{{ app.limit_mins or 30 }}"
                 min="1" max="1440" style="width:5rem;display:inline">
          <button type="submit" class="outline" style="font-size:0.75rem;padding:0.25rem 0.5rem">Set limit</button>
        </form>
      </div>
    </details>
  </td>
</tr>
```

Create `src/familylink_server/templates/apps.html`:

```html
{% extends "base.html" %}
{% block title %}Apps{% endblock %}
{% block content %}
<h2>Apps</h2>
<nav>
  {% for f in ["all", "allowed", "limited", "blocked"] %}
    <a href="/apps?filter={{ f }}"
       {% if filter == f %}aria-current="page"{% endif %}>{{ f | capitalize }}</a>
  {% endfor %}
</nav>
<table>
  <thead><tr><th>App</th><th>Status</th><th>Actions</th></tr></thead>
  <tbody>
    {% for app in apps %}
      {% include "partials/app_row.html" %}
    {% else %}
      <tr><td colspan="3">No apps found.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Register router in `main.py`:

```python
from familylink_server.routers.apps import router as apps_router
app.include_router(apps_router)
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
pytest tests/server/test_routers_apps.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/routers/apps.py src/familylink_server/templates/ tests/server/test_routers_apps.py
git commit -m "feat: add /apps page with HTMX inline edit for limit/block/allow"
```

---

### Task 10: Dashboard, History + base template

**Files:**
- Create: `src/familylink_server/routers/dashboard.py`
- Create: `src/familylink_server/routers/history.py`
- Create: `src/familylink_server/templates/base.html`
- Create: `src/familylink_server/templates/dashboard.html`
- Create: `src/familylink_server/templates/history.html`
- Modify: `src/familylink_server/main.py`
- Create: `tests/server/test_routers_dashboard.py`

**Interfaces:**
- Produces:
  - `GET /` → dashboard HTML
  - `GET /history` → history + audit log HTML (paginated with `?page=N`)

- [ ] **Step 1: Write failing tests**

```python
# tests/server/test_routers_dashboard.py
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
from itsdangerous import URLSafeSerializer
from familylink_server.config import settings


def _cookie():
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": settings.familylink_google_email})


def test_dashboard_returns_200():
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))
    with patch("familylink_server.services.family_link._service", mock_svc):
        from familylink_server.main import app
        client = TestClient(app)
    resp = client.get("/", cookies={"fl_session": _cookie()})
    assert resp.status_code == 200
    assert "Family Link" in resp.text


def test_history_returns_200():
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))
    with patch("familylink_server.services.family_link._service", mock_svc):
        from familylink_server.main import app
        client = TestClient(app)
    resp = client.get("/history", cookies={"fl_session": _cookie()})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/server/test_routers_dashboard.py -v
```

Expected: `404 Not Found` for `/`

- [ ] **Step 3: Create base.html**

Create `src/familylink_server/templates/base.html`:

```html
<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Family Link{% endblock %} — Family Link</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <script src="https://unpkg.com/htmx.org@1.9.12" defer></script>
</head>
<body>
  <header class="container">
    <nav>
      <ul><li><strong>Family Link</strong></li></ul>
      <ul>
        <li><a href="/">Dashboard</a></li>
        <li><a href="/apps">Apps</a></li>
        <li><a href="/devices">Devices</a></li>
        <li><a href="/history">History</a></li>
        <li><a href="/auth/logout" class="secondary">Logout</a></li>
      </ul>
    </nav>
  </header>
  <main class="container">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 4: Create dashboard router and template**

Create `src/familylink_server/routers/dashboard.py`:

```python
# src/familylink_server/routers/dashboard.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _email: str = Depends(require_user),
    svc: FamilyLinkService = Depends(get_service),
) -> HTMLResponse:
    members = await svc.get_members()
    children = [
        m for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    child_data = []
    for child in children:
        usage = await svc.get_apps_and_usage(child.user_id)
        total_seconds = sum(
            int(float(s.usage)) for s in usage.app_usage_sessions
        )
        top_apps: dict[str, int] = {}
        for s in usage.app_usage_sessions:
            pkg = s.app_id.android_app_package_name
            top_apps[pkg] = top_apps.get(pkg, 0) + int(float(s.usage))
        top5 = sorted(top_apps.items(), key=lambda x: x[1], reverse=True)[:5]
        top5_named = [
            {"title": usage.get_app_title(pkg), "seconds": secs}
            for pkg, secs in top5
        ]
        devices = [
            {"device_id": d.device_id, "friendly_name": d.display_info.friendly_name, "is_locked": False}
            for d in usage.device_info
        ]
        child_data.append({
            "display_name": child.profile.display_name,
            "user_id": child.user_id,
            "total_seconds": total_seconds,
            "top5": top5_named,
            "devices": devices,
        })
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "children": child_data},
    )
```

Create `src/familylink_server/templates/dashboard.html`:

```html
{% extends "base.html" %}
{% block title %}Dashboard{% endblock %}
{% block content %}
<div hx-get="/" hx-trigger="every 5m" hx-target="main" hx-swap="innerHTML">
  {% for child in children %}
    <section>
      <h2>{{ child.display_name }}</h2>
      <p>Today: <strong>{{ (child.total_seconds // 3600) }}h {{ ((child.total_seconds % 3600) // 60) }}m</strong></p>

      <h3>Top apps today</h3>
      {% set max_secs = child.top5[0].seconds if child.top5 else 1 %}
      {% for app in child.top5 %}
        <div style="margin-bottom:0.5rem">
          <span style="display:inline-block;width:12rem">{{ app.title }}</span>
          <span style="display:inline-block;background:var(--pico-primary);height:1rem;width:{{ (app.seconds / max_secs * 200) | int }}px;vertical-align:middle"></span>
          <span style="font-size:0.8rem;color:var(--pico-muted-color)">
            {{ app.seconds // 60 }}m
          </span>
        </div>
      {% endfor %}

      <h3>Devices</h3>
      <div class="grid">
        {% for device in child.devices %}
          <div class="card">
            <p>{{ device.friendly_name or device.device_id }}</p>
            {% if device.is_locked %}
              <span style="color:var(--pico-color-red-500)">Locked</span>
            {% else %}
              <span style="color:var(--pico-color-green-500)">Unlocked</span>
            {% endif %}
          </div>
        {% endfor %}
      </div>
    </section>
  {% else %}
    <p>No supervised children found.</p>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: Create history router and template**

Create `src/familylink_server/routers/history.py`:

```python
# src/familylink_server/routers/history.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import AuditLog, get_session

router = APIRouter(tags=["history"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
_PAGE_SIZE = 25


@router.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    page: int = 1,
    _email: str = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    offset = (page - 1) * _PAGE_SIZE
    q = select(AuditLog).order_by(desc(AuditLog.occurred_at)).offset(offset).limit(_PAGE_SIZE)
    logs = (await session.execute(q)).scalars().all()
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "logs": logs, "page": page, "has_more": len(logs) == _PAGE_SIZE},
    )
```

Create `src/familylink_server/templates/history.html`:

```html
{% extends "base.html" %}
{% block title %}History{% endblock %}
{% block content %}
<h2>Audit Log</h2>
<table>
  <thead>
    <tr>
      <th>When</th><th>Action</th><th>Target</th><th>Old</th><th>New</th>
    </tr>
  </thead>
  <tbody id="audit-rows">
    {% for log in logs %}
    <tr>
      <td>{{ log.occurred_at.strftime("%Y-%m-%d %H:%M") }}</td>
      <td>{{ log.action }}</td>
      <td>{{ log.target }}</td>
      <td>{{ log.old_value or "—" }}</td>
      <td>{{ log.new_value or "—" }}</td>
    </tr>
    {% else %}
    <tr><td colspan="5">No audit entries yet.</td></tr>
    {% endfor %}
    {% if has_more %}
    <tr id="load-more"
        hx-get="/history?page={{ page + 1 }}"
        hx-trigger="revealed"
        hx-target="#audit-rows"
        hx-swap="beforeend"
        hx-select="tbody tr">
      <td colspan="5" style="text-align:center;color:var(--pico-muted-color)">Loading…</td>
    </tr>
    {% endif %}
  </tbody>
</table>
{% endblock %}
```

Register both routers in `main.py`:

```python
from familylink_server.routers.dashboard import router as dashboard_router
from familylink_server.routers.history import router as history_router

app.include_router(dashboard_router)
app.include_router(history_router)
```

- [ ] **Step 6: Run tests — confirm they pass**

```bash
pytest tests/server/test_routers_dashboard.py -v
```

Expected: all PASS

- [ ] **Step 7: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/familylink_server/routers/ src/familylink_server/templates/ tests/server/test_routers_dashboard.py src/familylink_server/main.py
git commit -m "feat: add dashboard, history pages and base template"
```

---

### Task 11: Deployment config

**Files:**
- Create: `.env.example`
- Modify: `README.md` (add deployment section)

**Interfaces:**
- Produces: a working `Procfile` + documented env vars so the service can be deployed to Railway/Render/Fly.io

- [ ] **Step 1: Create .env.example**

```bash
# .env.example
DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname
SECRET_KEY=<random 32-byte hex: python -c "import secrets; print(secrets.token_hex(32))">
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
FAMILYLINK_GOOGLE_EMAIL=parent@gmail.com
FAMILYLINK_COOKIES_B64=<base64 output of: familylink export-cookies --base64>
CACHE_TTL_SECONDS=900
```

- [ ] **Step 2: Verify Procfile is correct**

Contents of `Procfile` (created in Task 1):

```
web: uvicorn familylink_server.main:app --host 0.0.0.0 --port $PORT
```

Confirm `$PORT` is the env var used by Railway/Render/Fly.io (all three use `PORT`).

- [ ] **Step 3: Add OAuth redirect URI note**

In `README.md` under a new `## Server Deployment` section, document:

1. Create a Google OAuth 2.0 Web Application credential at https://console.cloud.google.com/apis/credentials
2. Add the deployed URL's callback to **Authorized redirect URIs**: `https://<your-app>.railway.app/auth/callback`
3. Set all env vars from `.env.example` in your provider's dashboard
4. Run `alembic upgrade head` once (many providers run a release command — set it to `alembic upgrade head`)
5. `familylink export-cookies --base64` on your local machine, paste output to `FAMILYLINK_COOKIES_B64`

- [ ] **Step 4: Run full test suite one final time**

```bash
pytest tests/ -v --tb=short
```

Expected: all PASS, no warnings about missing env vars

- [ ] **Step 5: Commit**

```bash
git add .env.example README.md
git commit -m "docs: add deployment config and cloud setup instructions"
```
