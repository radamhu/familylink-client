# eKRÉTA Homework Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move eKRÉTA homework scraping/display out of the standalone `ekreta` repo and into `familylink-client`, so homework shows on the existing per-kid dashboard card and there's one repo/one deploy instead of two.

**Architecture:** A new `homework` router in `familylink_server` exposes two shared-secret-protected internal endpoints (`GET /internal/ekreta/credentials`, `POST /internal/ekreta/homework`) backed by two new Postgres tables. A separate `ekreta-scraper/` package (own Dockerfile, Playwright) keeps running on its own cron schedule exactly as it does today, except it now fetches its kid list from the API instead of `KID{N}_*` env vars, and POSTs results to the API instead of writing JSON files. The dashboard's existing per-child card gains a homework section fed by the new tables.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (async) + asyncpg, Alembic, Jinja2/HTMX, pytest/pytest-asyncio, httpx, Playwright (scraper only).

**Spec:** `docs/superpowers/specs/2026-09-08-ekreta-homework-migration-design.md`

## Global Constraints

- Internal endpoints authenticate via a shared-secret header (`X-Api-Key`, checked against `EKRETA_INGEST_TOKEN`) and **fail closed**: an unset or mismatched token always returns `401`, even in the current lax style used by `cookie_refresher_app.py` (`403` only when a key *is* configured) — these endpoints leak credentials/PII on `GET`, so no-token-configured must not mean open.
- No historical backfill — `homework_entries` starts empty; the ~30 days of JSON under the old `ekreta/data/` are not migrated.
- The scraper stays a separate runner/package (`ekreta-scraper/`), not folded into the `familylink_server` package — it has a heavy, unrelated dependency (Playwright/Chromium) that the main image should never need.
- No new public web page — homework only ever renders inside the existing dashboard's per-child expanded card.
- Retention default is 30 days (`EKRETA_RETENTION_DAYS`), pruned server-side on every ingest call — the scraper does not manage retention itself.
- The old `ekreta` git repo/directory is deleted once this plan's work is verified — not archived.

---

## File Structure

### `familylink-client` (server side)

- Modify `src/familylink_server/db/models.py` — add `EkretaCredential`, `HomeworkEntry`.
- Modify `src/familylink_server/db/__init__.py` — export the two new models.
- Create `src/familylink_server/db/homework.py` — query/mutation helpers (list credentials, replace a day's entries, prune, read a day's entries). Mirrors `db/app_config.py`'s role as the shared DB-logic layer for its router.
- Create `alembic/versions/005_ekreta_homework.py` — creates both tables.
- Modify `src/familylink_server/config.py` — add `ekreta_ingest_token`, `ekreta_retention_days`.
- Create `src/familylink_server/routers/homework.py` — the two internal endpoints.
- Modify `src/familylink_server/main.py` — register the new router.
- Modify `src/familylink_server/routers/dashboard.py` — `_get_child_data` gains a `homework` list.
- Modify `src/familylink_server/templates/partials/child_expanded.html` — render the homework list.
- Modify `.env.example`, `docker-compose.yml` — new env vars + new `ekreta-scraper` service.
- Tests: `tests/server/test_db_models.py` (extend), `tests/server/test_db_homework.py` (new), `tests/server/test_config.py` (extend), `tests/server/test_routers_homework.py` (new), `tests/server/test_routers_dashboard.py` (extend).

### `familylink-client/ekreta-scraper/` (new top-level directory, separate runner)

- `Dockerfile`, `entrypoint.sh` — copied unchanged from `ekreta/scraper/`.
- `requirements.txt`, `requirements-dev.txt` — add `httpx`.
- `pytest.ini` — copied unchanged.
- `src/config.py` — rewritten: `Kid` dataclass gains `child_id` (drops `name`), `fetch_kids()` replaces `load_kids()`/env parsing.
- `src/api_client.py` — new: `post_homework()`.
- `src/kreta_client.py` — copied unchanged (uses `kid.institution_code/username/password` only).
- `src/main.py` — rewritten: `run()` posts via `post_fn` instead of writing JSON; `main()` wires `fetch_kids`/`post_homework`.
- `src/storage.py` — dropped (no more JSON files).
- `tests/test_config.py`, `tests/test_main.py` — rewritten for the new interfaces.
- `tests/test_api_client.py` — new.
- `tests/test_kreta_client.py` — copied unchanged.

### Deleted at the end

- `/Users/ferko/development/ekreta/` (the whole standalone repo).

---

## Task 1: `EkretaCredential` and `HomeworkEntry` DB models

**Files:**
- Modify: `src/familylink_server/db/models.py`
- Modify: `src/familylink_server/db/__init__.py`
- Test: `tests/server/test_db_models.py`

**Interfaces:**
- Produces: `EkretaCredential(child_id: str, username: str, password: str, institution_code: str)`, `HomeworkEntry(child_id: str, date: date, subject: str, description: str, fetched_at: datetime)` — both SQLAlchemy ORM classes with an auto `id: int` primary key, importable from `familylink_server.db.models` and `familylink_server.db`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/server/test_db_models.py`:

```python
from familylink_server.db.models import EkretaCredential, HomeworkEntry


@pytest.mark.asyncio
async def test_ekreta_credential_insert_and_read(db_session):
    """Test EkretaCredential model insert and read operations."""
    cred = EkretaCredential(
        child_id='child1',
        username='anna.kovacs',
        password='secret',
        institution_code='035120',
    )
    db_session.add(cred)
    await db_session.commit()
    await db_session.refresh(cred)
    assert cred.id is not None
    assert cred.institution_code == '035120'


@pytest.mark.asyncio
async def test_homework_entry_insert_and_read(db_session):
    """Test HomeworkEntry model insert and read operations."""
    entry = HomeworkEntry(
        child_id='child1',
        date=date(2026, 9, 8),
        subject='Matek',
        description='Oldd meg a 12. feladatot.',
        fetched_at=datetime.now(UTC),
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    assert entry.id is not None
    assert entry.subject == 'Matek'
```

(`date`, `datetime`, `UTC`, `pytest` are already imported at the top of this file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_db_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'EkretaCredential'`

- [ ] **Step 3: Add the models**

In `src/familylink_server/db/models.py`, append after `LinuxUsageSnapshot`:

```python
class EkretaCredential(Base):
    """Login credentials for one kid's eKRÉTA (Hungarian school portal) account."""

    __tablename__ = 'ekreta_credentials'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(256), nullable=False)
    password: Mapped[str] = mapped_column(String(256), nullable=False)
    institution_code: Mapped[str] = mapped_column(String(32), nullable=False)


class HomeworkEntry(Base):
    """One scraped eKRÉTA homework item for a kid on a given date."""

    __tablename__ = 'homework_entries'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default='')
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

In `src/familylink_server/db/__init__.py`, add `EkretaCredential` and `HomeworkEntry` to both the import from `familylink_server.db.models` and `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_db_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/db/models.py src/familylink_server/db/__init__.py tests/server/test_db_models.py
git commit -m "feat: add EkretaCredential and HomeworkEntry models"
```

---

## Task 2: Alembic migration for the new tables

**Files:**
- Create: `alembic/versions/005_ekreta_homework.py`

**Interfaces:**
- Consumes: nothing new (raw `sa.Column`/`op` calls — schema must match Task 1's models exactly: `ekreta_credentials(id, child_id unique, username, password, institution_code)`, `homework_entries(id, child_id indexed, date, subject, description, fetched_at)`).

- [ ] **Step 1: Write the migration**

```python
"""add ekreta_credentials and homework_entries tables

Revision ID: 005
Revises: 004
Create Date: 2026-09-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '005'
down_revision: str | Sequence[str] | None = '004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ekreta_credentials and homework_entries tables."""
    op.create_table(
        'ekreta_credentials',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('child_id', sa.String(length=64), nullable=False),
        sa.Column('username', sa.String(length=256), nullable=False),
        sa.Column('password', sa.String(length=256), nullable=False),
        sa.Column('institution_code', sa.String(length=32), nullable=False),
    )
    op.create_unique_constraint(
        'uq_ekreta_credentials_child_id', 'ekreta_credentials', ['child_id']
    )
    op.create_table(
        'homework_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('child_id', sa.String(length=64), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('subject', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_homework_entries_child_id', 'homework_entries', ['child_id']
    )
    op.create_index(
        'ix_homework_entries_child_date', 'homework_entries', ['child_id', 'date']
    )


def downgrade() -> None:
    """Drop ekreta_credentials and homework_entries tables."""
    op.drop_index('ix_homework_entries_child_date', table_name='homework_entries')
    op.drop_index('ix_homework_entries_child_id', table_name='homework_entries')
    op.drop_table('homework_entries')
    op.drop_constraint(
        'uq_ekreta_credentials_child_id', 'ekreta_credentials', type_='unique'
    )
    op.drop_table('ekreta_credentials')
```

- [ ] **Step 2: Run the migration against the local/test DB**

Run: `alembic upgrade head`
Expected: no errors; `alembic current` reports `005 (head)`.

- [ ] **Step 3: Verify downgrade works too**

Run: `alembic downgrade 004 && alembic upgrade head`
Expected: both commands succeed with no errors.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/005_ekreta_homework.py
git commit -m "feat: add ekreta_credentials/homework_entries migration"
```

---

## Task 3: `EKRETA_INGEST_TOKEN` / `EKRETA_RETENTION_DAYS` settings

**Files:**
- Modify: `src/familylink_server/config.py`
- Test: `tests/server/test_config.py`

**Interfaces:**
- Produces: `settings.ekreta_ingest_token: str` (default `''`), `settings.ekreta_retention_days: int` (default `30`).

- [ ] **Step 1: Write the failing test**

Append to `tests/server/test_config.py`:

```python
def test_ekreta_settings_defaults():
    """Test that eKRÉTA ingest settings have sane defaults."""
    from familylink_server.config import Settings

    s = Settings()
    assert s.ekreta_ingest_token == ''
    assert s.ekreta_retention_days == 30


def test_ekreta_settings_from_env(monkeypatch):
    """Test that eKRÉTA ingest settings read from environment variables."""
    monkeypatch.setenv('EKRETA_INGEST_TOKEN', 'secret-token')
    monkeypatch.setenv('EKRETA_RETENTION_DAYS', '7')

    from familylink_server.config import Settings

    s = Settings()
    assert s.ekreta_ingest_token == 'secret-token'
    assert s.ekreta_retention_days == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_config.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'ekreta_ingest_token'`

- [ ] **Step 3: Add the settings**

In `src/familylink_server/config.py`, add two fields to `Settings` (near `refresher_api_key`):

```python
    ekreta_ingest_token: str = ''
    ekreta_retention_days: int = 30
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/config.py tests/server/test_config.py
git commit -m "feat: add EKRETA_INGEST_TOKEN/EKRETA_RETENTION_DAYS settings"
```

---

## Task 4: `db/homework.py` — homework/credentials DB helpers

**Files:**
- Create: `src/familylink_server/db/homework.py`
- Test: `tests/server/test_db_homework.py`

**Interfaces:**
- Consumes: `EkretaCredential`, `HomeworkEntry` from Task 1.
- Produces (all `async`, take an `AsyncSession` first arg):
  - `list_ekreta_credentials(session) -> list[EkretaCredential]`
  - `replace_homework_for_day(session, child_id: str, day: date, entries: list[dict[str, str]]) -> None` — `entries` items are `{'subject': str, 'description': str}`.
  - `prune_homework_before(session, child_id: str, cutoff: date) -> None`
  - `get_homework_for_day(session, child_id: str, day: date) -> list[HomeworkEntry]` — ordered by `subject`.

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_db_homework.py`:

```python
"""Tests for homework_entries/ekreta_credentials DB helpers (real in-memory DB)."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from familylink_server.db.homework import (
    get_homework_for_day,
    list_ekreta_credentials,
    prune_homework_before,
    replace_homework_for_day,
)
from familylink_server.db.models import Base, EkretaCredential, HomeworkEntry


@pytest.fixture
async def db_session():
    """Provide an in-memory SQLite session for testing."""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_ekreta_credentials_returns_all_rows(db_session):
    db_session.add(
        EkretaCredential(
            child_id='child1', username='u', password='p', institution_code='035120'
        )
    )
    await db_session.commit()
    rows = await list_ekreta_credentials(db_session)
    assert [r.child_id for r in rows] == ['child1']


@pytest.mark.asyncio
async def test_replace_homework_for_day_replaces_prior_entries(db_session):
    await replace_homework_for_day(
        db_session,
        'child1',
        date(2026, 9, 8),
        [{'subject': 'Old', 'description': 'stale'}],
    )
    await db_session.commit()
    await replace_homework_for_day(
        db_session,
        'child1',
        date(2026, 9, 8),
        [{'subject': 'Matek', 'description': 'new'}],
    )
    await db_session.commit()
    rows = await get_homework_for_day(db_session, 'child1', date(2026, 9, 8))
    assert [r.subject for r in rows] == ['Matek']


@pytest.mark.asyncio
async def test_replace_homework_for_day_leaves_other_days_alone(db_session):
    await replace_homework_for_day(
        db_session,
        'child1',
        date(2026, 9, 7),
        [{'subject': 'Yesterday', 'description': ''}],
    )
    await replace_homework_for_day(
        db_session, 'child1', date(2026, 9, 8), [{'subject': 'Today', 'description': ''}]
    )
    await db_session.commit()
    rows = await get_homework_for_day(db_session, 'child1', date(2026, 9, 7))
    assert [r.subject for r in rows] == ['Yesterday']


@pytest.mark.asyncio
async def test_prune_homework_before_deletes_old_rows_only(db_session):
    db_session.add(
        HomeworkEntry(
            child_id='child1',
            date=date(2020, 1, 1),
            subject='Ancient',
            description='',
            fetched_at=datetime.now(UTC),
        )
    )
    db_session.add(
        HomeworkEntry(
            child_id='child1',
            date=date(2026, 9, 8),
            subject='Recent',
            description='',
            fetched_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    await prune_homework_before(db_session, 'child1', date(2026, 8, 1))
    await db_session.commit()
    assert await get_homework_for_day(db_session, 'child1', date(2020, 1, 1)) == []
    rows = await get_homework_for_day(db_session, 'child1', date(2026, 9, 8))
    assert [r.subject for r in rows] == ['Recent']


@pytest.mark.asyncio
async def test_get_homework_for_day_orders_by_subject(db_session):
    await replace_homework_for_day(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {'subject': 'Torna', 'description': ''},
            {'subject': 'Angol', 'description': ''},
        ],
    )
    await db_session.commit()
    rows = await get_homework_for_day(db_session, 'child1', date(2026, 9, 8))
    assert [r.subject for r in rows] == ['Angol', 'Torna']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_db_homework.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'familylink_server.db.homework'`

- [ ] **Step 3: Write the implementation**

Create `src/familylink_server/db/homework.py`:

```python
"""Shared homework_entries / ekreta_credentials DB helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from familylink_server.db.models import EkretaCredential, HomeworkEntry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def list_ekreta_credentials(session: AsyncSession) -> list[EkretaCredential]:
    """Return every configured kid's eKRÉTA login."""
    result = await session.execute(select(EkretaCredential))
    return list(result.scalars().all())


async def replace_homework_for_day(
    session: AsyncSession,
    child_id: str,
    day: date,
    entries: list[dict[str, str]],
) -> None:
    """Replace a kid's homework rows for `day` with `entries`.

    Each entry is `{'subject': str, 'description': str}`.
    """
    await session.execute(
        delete(HomeworkEntry).where(
            HomeworkEntry.child_id == child_id, HomeworkEntry.date == day
        )
    )
    fetched_at = datetime.now(UTC)
    for entry in entries:
        session.add(
            HomeworkEntry(
                child_id=child_id,
                date=day,
                subject=entry['subject'],
                description=entry['description'],
                fetched_at=fetched_at,
            )
        )


async def prune_homework_before(
    session: AsyncSession, child_id: str, cutoff: date
) -> None:
    """Delete a kid's homework rows older than `cutoff`."""
    await session.execute(
        delete(HomeworkEntry).where(
            HomeworkEntry.child_id == child_id, HomeworkEntry.date < cutoff
        )
    )


async def get_homework_for_day(
    session: AsyncSession, child_id: str, day: date
) -> list[HomeworkEntry]:
    """Return a kid's homework rows for `day`, ordered by subject."""
    result = await session.execute(
        select(HomeworkEntry)
        .where(HomeworkEntry.child_id == child_id, HomeworkEntry.date == day)
        .order_by(HomeworkEntry.subject)
    )
    return list(result.scalars().all())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_db_homework.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/db/homework.py tests/server/test_db_homework.py
git commit -m "feat: add homework_entries/ekreta_credentials DB helpers"
```

---

## Task 5: `routers/homework.py` — internal credentials/ingest endpoints

**Files:**
- Create: `src/familylink_server/routers/homework.py`
- Modify: `src/familylink_server/main.py`
- Test: `tests/server/test_routers_homework.py`

**Interfaces:**
- Consumes: `settings.ekreta_ingest_token`, `settings.ekreta_retention_days` (Task 3); `list_ekreta_credentials`, `replace_homework_for_day`, `prune_homework_before` (Task 4); `get_session` from `familylink_server.db`.
- Produces: `router = APIRouter(...)` mounted at `/internal/ekreta` — `GET /internal/ekreta/credentials` → `200` `list[{"child_id","username","password","institution_code"}]` or `401`; `POST /internal/ekreta/homework` (body `{"child_id": str, "date": "YYYY-MM-DD", "entries": [{"subject": str, "teacher": str, "deadline": str, "text": str, "attachments": [str]}]}`) → `204` or `401`.

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_routers_homework.py`:

```python
"""Tests for the internal /internal/ekreta credentials/homework endpoints."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from familylink_server.config import settings
from familylink_server.db import get_session
from familylink_server.db.models import EkretaCredential


def _client():
    from familylink_server.main import app

    app.dependency_overrides[get_session] = lambda: AsyncMock()
    return TestClient(app)


def _pop_session_override():
    from familylink_server.main import app

    app.dependency_overrides.pop(get_session, None)


def test_credentials_requires_token(monkeypatch):
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    client = _client()
    try:
        resp = client.get('/internal/ekreta/credentials')
    finally:
        _pop_session_override()
    assert resp.status_code == 401


def test_credentials_rejects_when_no_token_configured(monkeypatch):
    """No configured token must mean 'closed', not 'open'."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', '')
    client = _client()
    try:
        resp = client.get(
            '/internal/ekreta/credentials', headers={'X-Api-Key': 'anything'}
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 401


def test_credentials_returns_rows(monkeypatch):
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    import familylink_server.routers.homework as homework_router

    monkeypatch.setattr(
        homework_router,
        'list_ekreta_credentials',
        AsyncMock(
            return_value=[
                EkretaCredential(
                    child_id='child1',
                    username='anna.kovacs',
                    password='pw',
                    institution_code='035120',
                )
            ]
        ),
    )
    client = _client()
    try:
        resp = client.get(
            '/internal/ekreta/credentials', headers={'X-Api-Key': 'secret'}
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 200
    assert resp.json() == [
        {
            'child_id': 'child1',
            'username': 'anna.kovacs',
            'password': 'pw',
            'institution_code': '035120',
        }
    ]


def test_ingest_requires_token():
    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={'child_id': 'child1', 'date': '2026-09-08', 'entries': []},
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 401


def test_ingest_replaces_and_prunes(monkeypatch):
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    monkeypatch.setattr(settings, 'ekreta_retention_days', 30)
    import familylink_server.routers.homework as homework_router

    replace_mock = AsyncMock()
    prune_mock = AsyncMock()
    monkeypatch.setattr(homework_router, 'replace_homework_for_day', replace_mock)
    monkeypatch.setattr(homework_router, 'prune_homework_before', prune_mock)
    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={
                'child_id': 'child1',
                'date': '2026-09-08',
                'entries': [
                    {
                        'subject': 'Matek',
                        'teacher': 'Kovács Tanárnő',
                        'deadline': '2026-09-09',
                        'text': 'Oldd meg a 12. feladatot.',
                        'attachments': [],
                    }
                ],
            },
            headers={'X-Api-Key': 'secret'},
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 204
    replace_mock.assert_awaited_once()
    call_args = replace_mock.await_args.args
    assert call_args[1] == 'child1'
    assert call_args[2].isoformat() == '2026-09-08'
    assert call_args[3] == [
        {
            'subject': 'Matek',
            'description': (
                'Teacher: Kovács Tanárnő\n'
                'Deadline: 2026-09-09\n'
                'Oldd meg a 12. feladatot.'
            ),
        }
    ]
    prune_mock.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_routers_homework.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'familylink_server.routers.homework'`

- [ ] **Step 3: Write the router**

Create `src/familylink_server/routers/homework.py`:

```python
"""Internal endpoints for the eKRÉTA scraper: credentials + homework ingest."""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.config import settings
from familylink_server.db import get_session
from familylink_server.db.homework import (
    list_ekreta_credentials,
    prune_homework_before,
    replace_homework_for_day,
)

router = APIRouter(prefix='/internal/ekreta', tags=['homework'])


def _require_ingest_token(x_api_key: str = Header(default='')) -> None:
    """Reject calls without the configured shared secret (fail closed)."""
    if not settings.ekreta_ingest_token or x_api_key != settings.ekreta_ingest_token:
        raise HTTPException(401, 'Unauthorized')


class CredentialOut(BaseModel):
    """One kid's eKRÉTA login, as returned to the scraper."""

    child_id: str
    username: str
    password: str
    institution_code: str


class HomeworkEntryIn(BaseModel):
    """One scraped homework item, matching kreta_client.parse_homework_entry()."""

    subject: str
    teacher: str = ''
    deadline: str = ''
    text: str = ''
    attachments: list[str] = []


class HomeworkIngestIn(BaseModel):
    """Body of POST /internal/ekreta/homework."""

    child_id: str
    date: date
    entries: list[HomeworkEntryIn]


def _format_description(entry: HomeworkEntryIn) -> str:
    """Render a scraped entry's teacher/deadline/text/attachments as display text."""
    lines = []
    if entry.teacher:
        lines.append(f'Teacher: {entry.teacher}')
    if entry.deadline:
        lines.append(f'Deadline: {entry.deadline}')
    if entry.text:
        lines.append(entry.text)
    if entry.attachments:
        lines.append('Attachments: ' + ', '.join(entry.attachments))
    return '\n'.join(lines)


@router.get('/credentials', response_model=list[CredentialOut])
async def get_credentials(
    _auth: None = Depends(_require_ingest_token),
    session: AsyncSession = Depends(get_session),
) -> list[CredentialOut]:
    """Return every configured kid's eKRÉTA login for the scraper to use."""
    rows = await list_ekreta_credentials(session)
    return [
        CredentialOut(
            child_id=row.child_id,
            username=row.username,
            password=row.password,
            institution_code=row.institution_code,
        )
        for row in rows
    ]


@router.post('/homework', status_code=204)
async def ingest_homework(
    body: HomeworkIngestIn,
    _auth: None = Depends(_require_ingest_token),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Replace a kid's homework for `body.date`, then prune rows past retention."""
    entries = [
        {'subject': e.subject, 'description': _format_description(e)}
        for e in body.entries
    ]
    await replace_homework_for_day(session, body.child_id, body.date, entries)
    cutoff = datetime.now(UTC).date() - timedelta(days=settings.ekreta_retention_days)
    await prune_homework_before(session, body.child_id, cutoff)
    await session.commit()
```

In `src/familylink_server/main.py`:
- Add the import next to the other router imports: `from familylink_server.routers.homework import router as homework_router`
- Add the registration next to the other `include_router` calls: `app.include_router(homework_router)`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_routers_homework.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/routers/homework.py src/familylink_server/main.py tests/server/test_routers_homework.py
git commit -m "feat: add internal /internal/ekreta credentials/homework endpoints"
```

---

## Task 6: Dashboard integration — homework on the per-kid card

**Files:**
- Modify: `src/familylink_server/routers/dashboard.py`
- Modify: `src/familylink_server/templates/partials/child_expanded.html`
- Test: `tests/server/test_routers_dashboard.py`

**Interfaces:**
- Consumes: `get_homework_for_day(session, child_id, day)` from Task 4.
- Produces: `_get_child_data()`'s returned dict gains `'homework': list[{'subject': str, 'description': str}]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/server/test_routers_dashboard.py`:

```python
def test_child_detail_shows_homework():
    """Expanded child card renders a homework entry for that child."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child = MagicMock()
    child.user_id = 'child1'
    child.profile.display_name = 'Alice'
    child.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    homework_row = MagicMock()
    homework_row.subject = 'Matek'
    homework_row.description = 'Oldd meg a 12. feladatot.'

    async def _gen():
        mock_session = AsyncMock()
        no_machines = MagicMock()
        no_machines.scalars.return_value.all.return_value = []
        with_homework = MagicMock()
        with_homework.scalars.return_value.all.return_value = [homework_row]
        mock_session.execute = AsyncMock(side_effect=[no_machines, with_homework])
        yield mock_session

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _gen
    try:
        client = TestClient(app)
        resp = client.get('/children/child1/detail', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Matek' in resp.text
    assert 'Oldd meg a 12. feladatot.' in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_routers_dashboard.py::test_child_detail_shows_homework -v`
Expected: FAIL (`assert 'Matek' in resp.text` — homework block doesn't exist yet)

- [ ] **Step 3: Wire homework into `_get_child_data` and the template**

In `src/familylink_server/routers/dashboard.py`, add the import:

```python
from familylink_server.db.homework import get_homework_for_day
```

In `_get_child_data`, after the `linux_rows` block and before `is_locked = ...`, add:

```python
    homework_rows = await get_homework_for_day(session, child.user_id, today)
    homework = [
        {'subject': h.subject, 'description': h.description} for h in homework_rows
    ]
```

Add `'homework': homework,` to the returned dict (next to `'linux_machines': linux_rows,`).

In `src/familylink_server/templates/partials/child_expanded.html`, add this block right after the Linux machines `{% if child.linux_machines %}...{% endif %}` block, still inside the outer padded `<div>`:

```html
  {% if child.homework %}
    <div style="font-size:10px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:5px;margin-top:10px">Homework today</div>
    {% for hw in child.homework %}
      <div style="font-size:11px;margin-bottom:6px">
        <div style="font-weight:600;color:#374151">{{ hw.subject }}</div>
        {% if hw.description %}
          <div style="color:#6b7280;white-space:pre-line">{{ hw.description }}</div>
        {% endif %}
      </div>
    {% endfor %}
  {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_routers_dashboard.py -v`
Expected: PASS (all tests, including the pre-existing ones — they tolerate the extra `execute()` call since `_fake_session` returns the same mock result for every call)

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/routers/dashboard.py src/familylink_server/templates/partials/child_expanded.html tests/server/test_routers_dashboard.py
git commit -m "feat: show today's homework on the dashboard child card"
```

---

## Task 7: `ekreta-scraper/src/config.py` — `Kid` + `fetch_kids`

**Files:**
- Create: `ekreta-scraper/src/config.py`
- Create: `ekreta-scraper/tests/test_config.py`

**Interfaces:**
- Produces: `Kid(child_id: str, username: str, password: str, institution_code: str)` (frozen dataclass), `fetch_kids(api_url: str, token: str) -> list[Kid]`, `load_cron_schedule(env: Mapping[str, str]) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `ekreta-scraper/tests/test_config.py`:

```python
import httpx
import pytest

from config import Kid, fetch_kids, load_cron_schedule


def test_fetch_kids_parses_response(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        assert url == "http://familylink-web:8000/internal/ekreta/credentials"
        assert headers == {"X-Api-Key": "secret-token"}
        return httpx.Response(
            200,
            json=[
                {
                    "child_id": "child1",
                    "username": "anna.kovacs",
                    "password": "pw",
                    "institution_code": "035120",
                }
            ],
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    kids = fetch_kids("http://familylink-web:8000", "secret-token")
    assert kids == [
        Kid(
            child_id="child1",
            username="anna.kovacs",
            password="pw",
            institution_code="035120",
        )
    ]


def test_fetch_kids_raises_on_http_error(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(
            401, json={"detail": "Unauthorized"}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(httpx.HTTPStatusError):
        fetch_kids("http://familylink-web:8000", "wrong-token")


def test_load_cron_schedule_default():
    assert load_cron_schedule({}) == "0 6 * * 1-5"


def test_load_cron_schedule_override():
    assert load_cron_schedule({"CRON_SCHEDULE": "0 7 * * *"}) == "0 7 * * *"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ekreta-scraper && python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Write the implementation**

Create `ekreta-scraper/src/config.py`:

```python
"""Kid config fetched from familylink-server's internal API."""

from dataclasses import dataclass
from typing import Mapping

import httpx


@dataclass(frozen=True)
class Kid:
    child_id: str
    username: str
    password: str
    institution_code: str


def fetch_kids(api_url: str, token: str) -> list[Kid]:
    """Fetch the configured kid list from familylink-server's internal API."""
    resp = httpx.get(
        f"{api_url}/internal/ekreta/credentials",
        headers={"X-Api-Key": token},
        timeout=30,
    )
    resp.raise_for_status()
    return [Kid(**row) for row in resp.json()]


def load_cron_schedule(env: Mapping[str, str]) -> str:
    return env.get("CRON_SCHEDULE", "0 6 * * 1-5")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ekreta-scraper && python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ekreta-scraper/src/config.py ekreta-scraper/tests/test_config.py
git commit -m "feat: fetch kid config from familylink-server API in ekreta-scraper"
```

---

## Task 8: `ekreta-scraper/src/api_client.py` — `post_homework`

**Files:**
- Create: `ekreta-scraper/src/api_client.py`
- Create: `ekreta-scraper/tests/test_api_client.py`

**Interfaces:**
- Consumes: nothing project-local (plain `httpx`).
- Produces: `post_homework(api_url: str, token: str, child_id: str, day: date, entries: list[dict]) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `ekreta-scraper/tests/test_api_client.py`:

```python
from datetime import date

import httpx
import pytest

from api_client import post_homework


def test_post_homework_sends_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    post_homework(
        "http://familylink-web:8000",
        "secret-token",
        "child1",
        date(2026, 9, 8),
        [{"subject": "Matek"}],
    )
    assert captured["url"] == "http://familylink-web:8000/internal/ekreta/homework"
    assert captured["headers"] == {"X-Api-Key": "secret-token"}
    assert captured["json"] == {
        "child_id": "child1",
        "date": "2026-09-08",
        "entries": [{"subject": "Matek"}],
    }


def test_post_homework_raises_on_http_error(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(httpx.HTTPStatusError):
        post_homework(
            "http://familylink-web:8000", "bad", "child1", date(2026, 9, 8), []
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ekreta-scraper && python -m pytest tests/test_api_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api_client'`

- [ ] **Step 3: Write the implementation**

Create `ekreta-scraper/src/api_client.py`:

```python
"""Posts scraped homework results back to familylink-server."""

from datetime import date

import httpx


def post_homework(
    api_url: str, token: str, child_id: str, day: date, entries: list[dict]
) -> None:
    """POST one kid's scraped homework for `day` to familylink-server."""
    resp = httpx.post(
        f"{api_url}/internal/ekreta/homework",
        headers={"X-Api-Key": token},
        json={"child_id": child_id, "date": day.isoformat(), "entries": entries},
        timeout=30,
    )
    resp.raise_for_status()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ekreta-scraper && python -m pytest tests/test_api_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ekreta-scraper/src/api_client.py ekreta-scraper/tests/test_api_client.py
git commit -m "feat: add post_homework API client for ekreta-scraper"
```

---

## Task 9: Port `kreta_client.py` unchanged

**Files:**
- Create: `ekreta-scraper/src/kreta_client.py` (copied from `../ekreta/scraper/src/kreta_client.py`)
- Create: `ekreta-scraper/tests/test_kreta_client.py` (copied from `../ekreta/scraper/tests/test_kreta_client.py`)

**Interfaces:**
- Consumes: `Kid` from Task 7 (`kreta_client.py` only reads `kid.institution_code`, `kid.username`, `kid.password` — all still present on the new `Kid`).
- Produces: `fetch_homework(page, kid: Kid) -> list[dict]`, `parse_homework_entry(raw: dict) -> dict`, `today_weekday_index(today: date) -> int`, `KretaClientError`.

- [ ] **Step 1: Copy the files verbatim**

```bash
cp /Users/ferko/development/ekreta/scraper/src/kreta_client.py ekreta-scraper/src/kreta_client.py
cp /Users/ferko/development/ekreta/scraper/tests/test_kreta_client.py ekreta-scraper/tests/test_kreta_client.py
```

- [ ] **Step 2: Run the copied tests as-is**

Run: `cd ekreta-scraper && python -m pytest tests/test_kreta_client.py -v`
Expected: PASS — the file imports `from config import Kid` and only uses `institution_code`/`username`/`password`, both of which Task 7's `Kid` still provides, so no edits are needed.

- [ ] **Step 3: Commit**

```bash
git add ekreta-scraper/src/kreta_client.py ekreta-scraper/tests/test_kreta_client.py
git commit -m "feat: port kreta_client.py into ekreta-scraper unchanged"
```

---

## Task 10: `ekreta-scraper/src/main.py` — post instead of write

**Files:**
- Create: `ekreta-scraper/src/main.py`
- Create: `ekreta-scraper/tests/test_main.py`

**Interfaces:**
- Consumes: `Kid`, `fetch_kids` (Task 7); `post_homework` (Task 8); `fetch_homework` (Task 9).
- Produces: `run(kids: list[Kid], api_url: str, token: str, fetch_fn, post_fn=post_homework, today=None) -> int` (`0` if every kid succeeded, `1` if any failed); `main() -> int`.

- [ ] **Step 1: Write the failing tests**

Create `ekreta-scraper/tests/test_main.py`:

```python
from datetime import date

from config import Kid
from main import run


def make_kid(child_id: str) -> Kid:
    return Kid(
        child_id=child_id,
        username=f"{child_id}-user",
        password="pw",
        institution_code="035120",
    )


def test_run_posts_entries_for_each_kid():
    kids = [make_kid("child1"), make_kid("child2")]
    fake_entries = {"child1": [{"subject": "Matek"}], "child2": []}
    posted = []

    def fake_post(api_url, token, child_id, day, entries):
        posted.append((api_url, token, child_id, day, entries))

    exit_code = run(
        kids=kids,
        api_url="http://familylink-web:8000",
        token="secret",
        fetch_fn=lambda kid: fake_entries[kid.child_id],
        post_fn=fake_post,
        today=date(2026, 9, 8),
    )

    assert exit_code == 0
    assert posted == [
        (
            "http://familylink-web:8000",
            "secret",
            "child1",
            date(2026, 9, 8),
            [{"subject": "Matek"}],
        ),
        ("http://familylink-web:8000", "secret", "child2", date(2026, 9, 8), []),
    ]


def test_run_continues_after_one_kid_fails():
    kids = [make_kid("child1"), make_kid("child2")]
    posted = []

    def fetch_fn(kid):
        if kid.child_id == "child1":
            raise RuntimeError("login failed")
        return []

    exit_code = run(
        kids=kids,
        api_url="http://familylink-web:8000",
        token="secret",
        fetch_fn=fetch_fn,
        post_fn=lambda *args: posted.append(args),
        today=date(2026, 9, 8),
    )

    assert exit_code == 1
    assert len(posted) == 1
    assert posted[0][2] == "child2"


def test_run_all_succeed_returns_zero():
    kids = [make_kid("child1")]
    exit_code = run(
        kids=kids,
        api_url="http://familylink-web:8000",
        token="secret",
        fetch_fn=lambda kid: [],
        post_fn=lambda *args: None,
        today=date(2026, 9, 8),
    )
    assert exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ekreta-scraper && python -m pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write the implementation**

Create `ekreta-scraper/src/main.py`:

```python
import sys
from datetime import date
from typing import Callable, Optional

from api_client import post_homework
from config import Kid, fetch_kids


def run(
    kids: list[Kid],
    api_url: str,
    token: str,
    fetch_fn: Callable[[Kid], list[dict]],
    post_fn: Callable[[str, str, str, date, list[dict]], None] = post_homework,
    today: Optional[date] = None,
) -> int:
    today = today or date.today()
    any_failed = False

    for kid in kids:
        try:
            entries = fetch_fn(kid)
        except Exception as exc:
            print(f"[ERROR] {kid.child_id}: {exc}", file=sys.stderr)
            any_failed = True
            continue
        post_fn(api_url, token, kid.child_id, today, entries)

    return 1 if any_failed else 0


def main() -> int:
    import os

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    from kreta_client import fetch_homework

    api_url = os.environ["FAMILYLINK_API_URL"]
    token = os.environ["EKRETA_INGEST_TOKEN"]
    kids = fetch_kids(api_url, token)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def fetch_fn(kid: Kid) -> list[dict]:
            for attempt in range(2):
                context = browser.new_context()
                try:
                    return fetch_homework(context.new_page(), kid)
                except PlaywrightTimeoutError:
                    if attempt == 1:
                        raise
                finally:
                    context.close()

        exit_code = run(kids, api_url, token, fetch_fn)
        browser.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ekreta-scraper && python -m pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ekreta-scraper/src/main.py ekreta-scraper/tests/test_main.py
git commit -m "feat: post scraped homework via API instead of writing JSON"
```

---

## Task 11: `ekreta-scraper` Docker packaging

**Files:**
- Create: `ekreta-scraper/Dockerfile` (copied from `../ekreta/scraper/Dockerfile`)
- Create: `ekreta-scraper/entrypoint.sh` (copied from `../ekreta/scraper/entrypoint.sh`)
- Create: `ekreta-scraper/requirements.txt`
- Create: `ekreta-scraper/requirements-dev.txt`
- Create: `ekreta-scraper/pytest.ini` (copied from `../ekreta/scraper/pytest.ini`)

**Interfaces:**
- Produces: a buildable Docker image whose entrypoint runs `ekreta-scraper/src/main.py` on `CRON_SCHEDULE`, forwarding whatever env vars the container was started with (including `FAMILYLINK_API_URL`, `EKRETA_INGEST_TOKEN`) into cron's job environment.

- [ ] **Step 1: Copy the Dockerfile, entrypoint, and pytest.ini verbatim**

```bash
cp /Users/ferko/development/ekreta/scraper/Dockerfile ekreta-scraper/Dockerfile
cp /Users/ferko/development/ekreta/scraper/entrypoint.sh ekreta-scraper/entrypoint.sh
cp /Users/ferko/development/ekreta/scraper/pytest.ini ekreta-scraper/pytest.ini
chmod +x ekreta-scraper/entrypoint.sh
```

These need no edits: the Dockerfile only copies `requirements.txt` and `src/`, and `entrypoint.sh` generically re-exports *every* env var the container has (not specific names), so it forwards `FAMILYLINK_API_URL`/`EKRETA_INGEST_TOKEN` to cron's job the same way it forwarded `KID{N}_*` before.

- [ ] **Step 2: Write requirements files**

Create `ekreta-scraper/requirements.txt`:

```
playwright==1.47.0
httpx==0.27.2
```

Create `ekreta-scraper/requirements-dev.txt`:

```
-r requirements.txt
pytest==8.3.3
```

- [ ] **Step 3: Build the image**

Run: `docker build -t ekreta-scraper-test ekreta-scraper/`
Expected: build succeeds (no errors); this is the task's test — there's no unit test for a Dockerfile.

- [ ] **Step 4: Commit**

```bash
git add ekreta-scraper/Dockerfile ekreta-scraper/entrypoint.sh ekreta-scraper/pytest.ini ekreta-scraper/requirements.txt ekreta-scraper/requirements-dev.txt
git commit -m "feat: add ekreta-scraper Docker packaging"
```

---

## Task 12: Wire `docker-compose.yml` and `.env.example`

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `ekreta-scraper` image from Task 11; `EKRETA_INGEST_TOKEN` setting from Task 3.
- Produces: a new `ekreta-scraper` service reachable by the `web` service at `http://web:8000` on the compose network, and `EKRETA_INGEST_TOKEN`/`FAMILYLINK_API_URL`/`CRON_SCHEDULE` env vars documented in `.env.example`.

- [ ] **Step 1: Add the service to `docker-compose.yml`**

In `docker-compose.yml`, add a new service (after `cookie-refresher`, before `firefox`):

```yaml
  ekreta-scraper:
    build: ./ekreta-scraper
    restart: unless-stopped
    environment:
      FAMILYLINK_API_URL: http://web:8000
      EKRETA_INGEST_TOKEN: ${EKRETA_INGEST_TOKEN:?EKRETA_INGEST_TOKEN is required}
      CRON_SCHEDULE: ${EKRETA_CRON_SCHEDULE:-0 6 * * 1-5}
    depends_on:
      - web
```

Add `EKRETA_INGEST_TOKEN` to the `web` service's `environment:` block:

```yaml
      EKRETA_INGEST_TOKEN: ${EKRETA_INGEST_TOKEN:?EKRETA_INGEST_TOKEN is required}
```

- [ ] **Step 2: Document the env vars in `.env.example`**

In `.env.example`, add a new section (after the cookie-refresher sidecar section):

```
# ------------------------------------------
# eKRÉTA homework scraper (optional — enables homework on the dashboard)
# Set on BOTH the main server and the ekreta-scraper service.
# ------------------------------------------

# Shared secret — must match on both the web service and ekreta-scraper
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
# EKRETA_INGEST_TOKEN=<random 32-byte hex>

# How many days of homework to keep (server-side, pruned on each scrape)
# EKRETA_RETENTION_DAYS=30

# Cron schedule for the scraper container (default: weekdays 06:00)
# EKRETA_CRON_SCHEDULE=0 6 * * 1-5
```

- [ ] **Step 3: Validate the compose file**

Run: `docker compose config --quiet`
Expected: no errors (confirms YAML is valid and required env vars are referenced correctly).

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat: wire ekreta-scraper into docker-compose"
```

---

## Task 13: Remove the standalone `ekreta` repo

**Files:**
- Delete: `/Users/ferko/development/ekreta/` (entire directory/repo)

**Interfaces:** none — terminal task.

- [ ] **Step 1: Confirm the full familylink-client test suite passes first**

Run: `python -m pytest`
Expected: PASS (all tests, including every test added in Tasks 1–10)

- [ ] **Step 2: Confirm the ekreta-scraper suite passes**

Run: `cd ekreta-scraper && python -m pytest`
Expected: PASS

- [ ] **Step 3: Delete the old repo**

```bash
rm -rf /Users/ferko/development/ekreta
```

- [ ] **Step 4: Report completion**

No commit — the deleted repo is outside `familylink-client`. Confirm to the user that `/Users/ferko/development/ekreta` is gone and that homework now runs entirely from `familylink-client` + `ekreta-scraper/`.
