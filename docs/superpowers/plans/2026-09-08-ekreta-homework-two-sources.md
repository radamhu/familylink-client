# eKRÉTA Homework: Second Source + Deadline Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrape homework from both the Órarend (timetable) page and the `Tanulo/TanuloHaziFeladat` (homework list) page, merge/dedupe what they report about the same assignment, and switch the dashboard from "today's homework" to "homework due" — showing every entry from the day it's scraped until its deadline passes.

**Architecture:** `homework_entries` gains a `deadline` column and a `(child_id, subject, deadline)` uniqueness constraint that becomes the identity of one homework item, replacing the old "replace this day's batch" model with upsert-by-identity. The scraper's `fetch_homework()` becomes an orchestrator over two independently-wrapped source scrapes whose results are merged by `(subject, deadline)` and filtered to `deadline >= today` before posting. The ingest endpoint and dashboard query both move from day-scoped to deadline-scoped.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (async) + aiosqlite (tests) / asyncpg (prod), Alembic, Jinja2/HTMX, pytest/pytest-asyncio, httpx, Playwright (scraper only).

**Spec:** `docs/superpowers/specs/2026-09-08-ekreta-homework-two-sources-design.md`

## Global Constraints

- Identity key for a homework item is `(child_id, subject, deadline)` — re-scraping a still-open item upserts in place, never duplicates.
- The scraper filters to `deadline >= today` before posting; the server stays a dumb store (no scraper-side dedup against prior runs — DB upsert handles that).
- A homework row disappears from the dashboard the day *after* its deadline (`deadline >= today` is the visibility rule, matching `prune_expired_homework`'s `deadline < today` deletion rule).
- Each source scrape (Órarend, Házi Feladatok) is wrapped independently — one page's failure doesn't drop the other page's results for that kid. A single unparseable homework row is logged and dropped, not fatal to the rest of the batch.
- `Házi Feladatok` list-page selectors are unverified against the live site (unlike Órarend's, confirmed 2026-09-08) — Task 7 implements a best-effort version driven by the one known fact (the `"Házi feladat határideje"` column header text) and flags what needs live-site verification before this ships.
- `ekreta_retention_days` / `EKRETA_RETENTION_DAYS` become dead config — pruning is now deadline-driven, not day-count-driven — and are removed.

---

## File Structure

### `familylink-client` (server side)

- Create: `alembic/versions/006_homework_deadline.py` — adds `deadline` column + unique constraint.
- Modify: `src/familylink_server/db/models.py` — `HomeworkEntry` gains `deadline`, unique constraint.
- Modify: `src/familylink_server/db/homework.py` — `upsert_homework_entries`/`prune_expired_homework`/`get_upcoming_homework` replace the day-bucket functions.
- Modify: `src/familylink_server/config.py` — remove `ekreta_retention_days`.
- Modify: `src/familylink_server/routers/homework.py` — new ingest payload shape (no top-level `date`, entries carry `deadline`).
- Modify: `src/familylink_server/routers/dashboard.py` — `_get_child_data` uses `get_upcoming_homework`.
- Modify: `src/familylink_server/templates/partials/child_expanded.html` — "Homework due", shows deadline.
- Modify: `.env.example` — drop `EKRETA_RETENTION_DAYS`.
- Tests: `tests/server/test_db_models.py`, `tests/server/test_db_homework.py`, `tests/server/test_config.py`, `tests/server/test_routers_homework.py`, `tests/server/test_routers_dashboard.py` (all modified in place).

### `familylink-client/ekreta-scraper/`

- Modify: `src/kreta_client.py` — split into `_login`/`_scrape_orarend`/`_scrape_haza_feladatok`/`_parse_hun_date`/`_merge_homework_entries`/`_filter_upcoming`, with `fetch_homework` as the orchestrator.
- Modify: `src/api_client.py` — `post_homework` drops the `day` parameter.
- Modify: `src/main.py` — `run()` drops `today`/`day` threading to `post_fn`.
- Tests: `tests/test_kreta_client.py`, `tests/test_api_client.py`, `tests/test_main.py` (all modified in place).

---

## Task 1: Migration `006` — `deadline` column + identity constraint

**Files:**
- Create: `alembic/versions/006_homework_deadline.py`

**Interfaces:**
- Produces: `homework_entries.deadline` (Date, not null), unique constraint `uq_homework_entries_child_subject_deadline` on `(child_id, subject, deadline)`. Must match Task 2's model exactly.

- [ ] **Step 1: Write the migration**

```python
"""add deadline column and identity constraint to homework_entries

Revision ID: 006
Revises: 005
Create Date: 2026-09-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '006'
down_revision: str | Sequence[str] | None = '005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add deadline column and (child_id, subject, deadline) uniqueness."""
    op.add_column(
        'homework_entries', sa.Column('deadline', sa.Date(), nullable=False)
    )
    op.create_unique_constraint(
        'uq_homework_entries_child_subject_deadline',
        'homework_entries',
        ['child_id', 'subject', 'deadline'],
    )


def downgrade() -> None:
    """Drop deadline column and its uniqueness constraint."""
    op.drop_constraint(
        'uq_homework_entries_child_subject_deadline',
        'homework_entries',
        type_='unique',
    )
    op.drop_column('homework_entries', 'deadline')
```

- [ ] **Step 2: Run the migration against the local/test DB**

Run: `alembic upgrade head`
Expected: no errors; `alembic current` reports `006 (head)`.

- [ ] **Step 3: Verify downgrade works too**

Run: `alembic downgrade 005 && alembic upgrade head`
Expected: both commands succeed with no errors.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/006_homework_deadline.py
git commit -m "feat: add deadline column/identity constraint to homework_entries

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: `HomeworkEntry` model — `deadline` + unique constraint

**Files:**
- Modify: `src/familylink_server/db/models.py:163-177`
- Test: `tests/server/test_db_models.py:1-15` (import), `:182-212` (existing homework tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `HomeworkEntry(child_id, date, deadline, subject, description, fetched_at)` — `deadline: date`, non-null. `HomeworkEntry.__table__` carries both `ix_homework_entries_child_date` and `uq_homework_entries_child_subject_deadline`.

- [ ] **Step 1: Write the failing tests**

Replace `tests/server/test_db_models.py:182-198` (the body of `test_homework_entry_insert_and_read`) with:

```python
@pytest.mark.asyncio
async def test_homework_entry_insert_and_read(db_session):
    """Test HomeworkEntry model insert and read operations."""
    from familylink_server.db.models import HomeworkEntry

    entry = HomeworkEntry(
        child_id='child1',
        date=date(2026, 9, 8),
        deadline=date(2026, 9, 10),
        subject='Matek',
        description='Oldd meg a 12. feladatot.',
        fetched_at=datetime.now(UTC),
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    assert entry.id is not None
    assert entry.subject == 'Matek'
    assert entry.deadline == date(2026, 9, 10)
```

Append after `test_homework_entry_has_composite_child_date_index` (end of file):

```python


def test_homework_entry_has_unique_child_subject_deadline_constraint():
    """Test that HomeworkEntry declares the same uniqueness as the migration."""
    from familylink_server.db.models import HomeworkEntry

    constraints = {
        c.name: [col.name for col in c.columns]
        for c in HomeworkEntry.__table__.constraints
        if c.name
    }
    assert constraints['uq_homework_entries_child_subject_deadline'] == [
        'child_id',
        'subject',
        'deadline',
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_db_models.py -v`
Expected: FAIL — `test_homework_entry_insert_and_read` errors with `TypeError` (unexpected keyword `deadline`); the new constraint test fails with `KeyError`.

- [ ] **Step 3: Update the model**

Replace `src/familylink_server/db/models.py:163-177` with:

```python
class HomeworkEntry(Base):
    """One scraped eKRÉTA homework item for a kid, open until its deadline."""

    __tablename__ = 'homework_entries'
    __table_args__ = (
        Index('ix_homework_entries_child_date', 'child_id', 'date'),
        UniqueConstraint(
            'child_id',
            'subject',
            'deadline',
            name='uq_homework_entries_child_subject_deadline',
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    deadline: Mapped[date] = mapped_column(Date, nullable=False)
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default='')
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_db_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/db/models.py tests/server/test_db_models.py
git commit -m "feat: add deadline field to HomeworkEntry model

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `db/homework.py` — identity-based upsert/prune/query

**Files:**
- Modify: `src/familylink_server/db/homework.py` (full rewrite)
- Test: `tests/server/test_db_homework.py` (full rewrite)

**Interfaces:**
- Consumes: `HomeworkEntry`, `EkretaCredential` from Task 2.
- Produces (all `async`, take an `AsyncSession` first arg):
  - `list_ekreta_credentials(session) -> list[EkretaCredential]` (unchanged)
  - `upsert_homework_entries(session, child_id: str, today: date, entries: list[dict]) -> None` — `entries` items are `{'subject': str, 'deadline': date, 'description': str}`.
  - `prune_expired_homework(session, child_id: str, today: date) -> None`
  - `get_upcoming_homework(session, child_id: str, today: date) -> list[HomeworkEntry]` — `deadline >= today`, ordered by `(deadline, subject)`.

- [ ] **Step 1: Write the failing tests**

Replace `tests/server/test_db_homework.py` entirely with:

```python
"""Tests for homework_entries/ekreta_credentials DB helpers (real in-memory DB)."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from familylink_server.db.homework import (
    get_upcoming_homework,
    list_ekreta_credentials,
    prune_expired_homework,
    upsert_homework_entries,
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
async def test_upsert_inserts_new_entry(db_session):
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {
                'subject': 'Matek',
                'deadline': date(2026, 9, 10),
                'description': 'new',
            }
        ],
    )
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2026, 9, 8))
    assert [(r.subject, r.description) for r in rows] == [('Matek', 'new')]


@pytest.mark.asyncio
async def test_upsert_refreshes_existing_entry_same_identity(db_session):
    """Same (child_id, subject, deadline) scraped again refreshes, not duplicates."""
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [{'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'stale'}],
    )
    await db_session.commit()
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 9),
        [{'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'fresh'}],
    )
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2026, 9, 8))
    assert [(r.subject, r.description, r.date) for r in rows] == [
        ('Matek', 'fresh', date(2026, 9, 9))
    ]


@pytest.mark.asyncio
async def test_upsert_keeps_distinct_subject_same_deadline_separate(db_session):
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'a'},
            {'subject': 'Angol', 'deadline': date(2026, 9, 10), 'description': 'b'},
        ],
    )
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2026, 9, 8))
    assert sorted(r.subject for r in rows) == ['Angol', 'Matek']


@pytest.mark.asyncio
async def test_prune_expired_homework_deletes_past_deadline_only(db_session):
    db_session.add(
        HomeworkEntry(
            child_id='child1',
            date=date(2026, 9, 1),
            deadline=date(2026, 9, 7),
            subject='Old',
            description='',
            fetched_at=datetime.now(UTC),
        )
    )
    db_session.add(
        HomeworkEntry(
            child_id='child1',
            date=date(2026, 9, 8),
            deadline=date(2026, 9, 10),
            subject='Recent',
            description='',
            fetched_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    await prune_expired_homework(db_session, 'child1', date(2026, 9, 8))
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2020, 1, 1))
    assert [r.subject for r in rows] == ['Recent']


@pytest.mark.asyncio
async def test_get_upcoming_homework_excludes_past_deadlines(db_session):
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {'subject': 'Past', 'deadline': date(2026, 9, 7), 'description': ''},
            {'subject': 'Today', 'deadline': date(2026, 9, 8), 'description': ''},
            {'subject': 'Future', 'deadline': date(2026, 9, 9), 'description': ''},
        ],
    )
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2026, 9, 8))
    assert [r.subject for r in rows] == ['Today', 'Future']


@pytest.mark.asyncio
async def test_get_upcoming_homework_orders_by_deadline_then_subject(db_session):
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {'subject': 'Torna', 'deadline': date(2026, 9, 9), 'description': ''},
            {'subject': 'Angol', 'deadline': date(2026, 9, 9), 'description': ''},
            {'subject': 'Matek', 'deadline': date(2026, 9, 8), 'description': ''},
        ],
    )
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2026, 9, 8))
    assert [r.subject for r in rows] == ['Matek', 'Angol', 'Torna']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_db_homework.py -v`
Expected: FAIL with `ImportError: cannot import name 'upsert_homework_entries'`

- [ ] **Step 3: Rewrite the implementation**

Replace `src/familylink_server/db/homework.py` entirely with:

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


async def upsert_homework_entries(
    session: AsyncSession,
    child_id: str,
    today: date,
    entries: list[dict[str, str | date]],
) -> None:
    """Insert-or-refresh a kid's homework, keyed by (child_id, subject, deadline).

    Each entry is `{'subject': str, 'deadline': date, 'description': str}`. A
    still-open item scraped again refreshes its description/date/fetched_at
    in place rather than duplicating.
    """
    fetched_at = datetime.now(UTC)
    for entry in entries:
        existing = (
            await session.execute(
                select(HomeworkEntry).where(
                    HomeworkEntry.child_id == child_id,
                    HomeworkEntry.subject == entry['subject'],
                    HomeworkEntry.deadline == entry['deadline'],
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.description = entry['description']
            existing.date = today
            existing.fetched_at = fetched_at
        else:
            session.add(
                HomeworkEntry(
                    child_id=child_id,
                    date=today,
                    subject=entry['subject'],
                    deadline=entry['deadline'],
                    description=entry['description'],
                    fetched_at=fetched_at,
                )
            )


async def prune_expired_homework(
    session: AsyncSession, child_id: str, today: date
) -> None:
    """Delete a kid's homework rows whose deadline has already passed."""
    await session.execute(
        delete(HomeworkEntry).where(
            HomeworkEntry.child_id == child_id, HomeworkEntry.deadline < today
        )
    )


async def get_upcoming_homework(
    session: AsyncSession, child_id: str, today: date
) -> list[HomeworkEntry]:
    """Return a kid's not-yet-due homework, ordered by deadline then subject."""
    result = await session.execute(
        select(HomeworkEntry)
        .where(HomeworkEntry.child_id == child_id, HomeworkEntry.deadline >= today)
        .order_by(HomeworkEntry.deadline, HomeworkEntry.subject)
    )
    return list(result.scalars().all())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_db_homework.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/db/homework.py tests/server/test_db_homework.py
git commit -m "feat: switch homework DB layer to identity-based upsert/prune

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: Drop `ekreta_retention_days` (dead config)

**Files:**
- Modify: `src/familylink_server/config.py:28-29`
- Modify: `.env.example:110-111`
- Test: `tests/server/test_config.py:64-82`

**Interfaces:**
- Produces: `settings.ekreta_ingest_token: str` (unchanged). `settings.ekreta_retention_days` no longer exists.

- [ ] **Step 1: Update the tests**

Replace `tests/server/test_config.py:64-82` with:

```python
def test_ekreta_settings_defaults():
    """Test that eKRÉTA ingest settings have sane defaults."""
    from familylink_server.config import Settings

    s = Settings()
    assert s.ekreta_ingest_token == ''


def test_ekreta_settings_from_env(monkeypatch):
    """Test that eKRÉTA ingest settings read from environment variables."""
    monkeypatch.setenv('EKRETA_INGEST_TOKEN', 'secret-token')

    from familylink_server.config import Settings

    s = Settings()
    assert s.ekreta_ingest_token == 'secret-token'
```

- [ ] **Step 2: Run tests to verify current behavior still passes (no red step here — this is a deletion)**

Run: `python -m pytest tests/server/test_config.py -v`
Expected: PASS (the trimmed tests don't reference the field being removed, so nothing fails yet)

- [ ] **Step 3: Remove the setting**

In `src/familylink_server/config.py`, delete line 29 (`ekreta_retention_days: int = 30`), keeping line 28 (`ekreta_ingest_token: str = ''`).

In `.env.example`, delete lines 110-111:
```
# How many days of homework to keep (server-side, pruned on each scrape)
# EKRETA_RETENTION_DAYS=30

```
(the blank line after stays as the separator before the cron-schedule comment).

- [ ] **Step 4: Run tests to verify they still pass**

Run: `python -m pytest tests/server/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/config.py .env.example tests/server/test_config.py
git commit -m "chore: remove dead EKRETA_RETENTION_DAYS setting

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: Ingest endpoint — deadline-carrying entries, no top-level date

**Files:**
- Modify: `src/familylink_server/routers/homework.py`
- Test: `tests/server/test_routers_homework.py`

**Interfaces:**
- Consumes: `upsert_homework_entries`, `prune_expired_homework` (Task 3); `settings.ekreta_ingest_token` (Task 4).
- Produces: `POST /internal/ekreta/homework` body `{"child_id": str, "entries": [{"subject": str, "teacher": str, "deadline": "YYYY-MM-DD", "text": str, "attachments": [str]}]}` → `204` or `401`. `GET /internal/ekreta/credentials` unchanged.

- [ ] **Step 1: Write the failing tests**

Replace the `test_ingest_requires_token` and `test_ingest_replaces_and_prunes` tests (and imports) in `tests/server/test_routers_homework.py`. Full new file:

```python
"""Tests for the internal /internal/ekreta credentials/homework endpoints."""

from datetime import date
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from freezegun import freeze_time

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


def test_credentials_rejects_same_length_wrong_token(monkeypatch):
    """A wrong token of the same length must still be rejected (constant-time compare)."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    client = _client()
    try:
        resp = client.get(
            '/internal/ekreta/credentials', headers={'X-Api-Key': 'wr0ng!'}
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
            json={'child_id': 'child1', 'entries': []},
        )
    finally:
        _pop_session_override()
    assert resp.status_code == 401


@freeze_time('2026-09-08')
def test_ingest_upserts_and_prunes(monkeypatch):
    """Time is frozen so the asserted 'today' never drifts."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    import familylink_server.routers.homework as homework_router

    upsert_mock = AsyncMock()
    prune_mock = AsyncMock()
    monkeypatch.setattr(homework_router, 'upsert_homework_entries', upsert_mock)
    monkeypatch.setattr(homework_router, 'prune_expired_homework', prune_mock)
    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={
                'child_id': 'child1',
                'entries': [
                    {
                        'subject': 'Matek',
                        'teacher': 'Kovács Tanárnő',
                        'deadline': '2026-09-10',
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
    upsert_mock.assert_awaited_once()
    call_args = upsert_mock.await_args.args
    assert call_args[1] == 'child1'
    assert call_args[2] == date(2026, 9, 8)
    assert call_args[3] == [
        {
            'subject': 'Matek',
            'deadline': date(2026, 9, 10),
            'description': 'Teacher: Kovács Tanárnő\nOldd meg a 12. feladatot.',
        }
    ]
    prune_mock.assert_awaited_once()
    prune_call_args = prune_mock.await_args.args
    assert prune_call_args[1] == 'child1'
    assert prune_call_args[2] == date(2026, 9, 8)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_routers_homework.py -v`
Expected: FAIL — old tests reference `replace_homework_for_day`/`prune_homework_before` which no longer exist in `db/homework.py` (Task 3 already removed them), so imports/monkeypatches error.

- [ ] **Step 3: Rewrite the router**

Replace `src/familylink_server/routers/homework.py` entirely with:

```python
"""Internal endpoints for the eKRÉTA scraper: credentials + homework ingest."""

import logging
import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.config import settings
from familylink_server.db import get_session
from familylink_server.db.homework import (
    list_ekreta_credentials,
    prune_expired_homework,
    upsert_homework_entries,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix='/internal/ekreta', tags=['homework'], include_in_schema=False
)


def _require_ingest_token(x_api_key: str = Header(default='')) -> None:
    """Reject calls without the configured shared secret (fail closed)."""
    if not settings.ekreta_ingest_token or not secrets.compare_digest(
        x_api_key, settings.ekreta_ingest_token
    ):
        logger.warning('eKRÉTA ingest auth failed')
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
    deadline: date
    text: str = ''
    attachments: list[str] = []


class HomeworkIngestIn(BaseModel):
    """Body of POST /internal/ekreta/homework."""

    child_id: str
    entries: list[HomeworkEntryIn]


def _format_description(entry: HomeworkEntryIn) -> str:
    """Render a scraped entry's teacher/text/attachments as display text.

    The deadline is not included here — it's a first-class column, shown
    separately by the dashboard.
    """
    lines = []
    if entry.teacher:
        lines.append(f'Teacher: {entry.teacher}')
    if entry.text:
        lines.append(entry.text)
    if entry.attachments:
        lines.append('Attachments: ' + ', '.join(entry.attachments))
    return '\n'.join(lines)


@router.get('/credentials', response_model=list[CredentialOut])
async def get_credentials(
    _auth: None = Depends(_require_ingest_token),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
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
    _auth: None = Depends(_require_ingest_token),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Upsert a kid's homework by identity, then prune expired rows."""
    today = date.today()
    entries = [
        {
            'subject': e.subject,
            'deadline': e.deadline,
            'description': _format_description(e),
        }
        for e in body.entries
    ]
    await upsert_homework_entries(session, body.child_id, today, entries)
    await prune_expired_homework(session, body.child_id, today)
    await session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_routers_homework.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/routers/homework.py tests/server/test_routers_homework.py
git commit -m "feat: switch homework ingest to deadline-carrying entries

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Dashboard — "homework due", not "homework today"

**Files:**
- Modify: `src/familylink_server/routers/dashboard.py:16` (import), `:93-96` (child data build)
- Modify: `src/familylink_server/templates/partials/child_expanded.html:67-77`
- Test: `tests/server/test_routers_dashboard.py:246-289`

**Interfaces:**
- Consumes: `get_upcoming_homework(session, child_id, today)` from Task 3.
- Produces: `_get_child_data()`'s dict gains `'homework': list[{'subject': str, 'description': str, 'deadline': str}]`, ordered by deadline then subject.

- [ ] **Step 1: Write the failing test**

Replace `tests/server/test_routers_dashboard.py:246-289` (`test_child_detail_shows_homework`) with:

```python
def test_child_detail_shows_upcoming_homework():
    """Expanded child card renders a not-yet-due homework entry, with its deadline."""
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
    homework_row.deadline = date(2026, 9, 10)

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
    assert '2026-09-10' in resp.text


def test_child_detail_hides_homework_section_when_none_upcoming():
    """No 'Homework due' section when the DB query returns nothing (e.g. all expired)."""
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

    async def _gen():
        mock_session = AsyncMock()
        no_machines = MagicMock()
        no_machines.scalars.return_value.all.return_value = []
        no_homework = MagicMock()
        no_homework.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[no_machines, no_homework])
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
    assert 'Homework due' not in resp.text
```

(`date` is already imported at the top of this test file — confirm and add `from datetime import date` if not already present.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_routers_dashboard.py::test_child_detail_shows_upcoming_homework tests/server/test_routers_dashboard.py::test_child_detail_hides_homework_section_when_none_upcoming -v`
Expected: FAIL (`assert '2026-09-10' in resp.text` — deadline isn't rendered yet; also `get_homework_for_day` no longer exists, so the router import itself is broken until Step 3)

- [ ] **Step 3: Wire `get_upcoming_homework` into the router and template**

In `src/familylink_server/routers/dashboard.py:16`, change:

```python
from familylink_server.db.homework import get_homework_for_day
```

to:

```python
from familylink_server.db.homework import get_upcoming_homework
```

In `src/familylink_server/routers/dashboard.py:93-96`, change:

```python
    homework_rows = await get_homework_for_day(session, child.user_id, today)
    homework = [
        {'subject': h.subject, 'description': h.description} for h in homework_rows
    ]
```

to:

```python
    homework_rows = await get_upcoming_homework(session, child.user_id, today)
    homework = [
        {
            'subject': h.subject,
            'description': h.description,
            'deadline': h.deadline.isoformat(),
        }
        for h in homework_rows
    ]
```

In `src/familylink_server/templates/partials/child_expanded.html:67-77`, replace:

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

with:

```html
  {% if child.homework %}
    <div style="font-size:10px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:5px;margin-top:10px">Homework due</div>
    {% for hw in child.homework %}
      <div style="font-size:11px;margin-bottom:6px">
        <div style="font-weight:600;color:#374151">{{ hw.subject }} <span style="font-weight:400;color:#9ca3af">— due {{ hw.deadline }}</span></div>
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
git commit -m "feat: show homework due (not just today) on the dashboard

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: `kreta_client.py` — two-source scrape, merge, filter

**Files:**
- Modify: `ekreta-scraper/src/kreta_client.py` (full rewrite)
- Test: `ekreta-scraper/tests/test_kreta_client.py` (full rewrite)

**Interfaces:**
- Consumes: `Kid` from `config.py` (unchanged).
- Produces: `fetch_homework(page, kid: Kid) -> list[dict]` (orchestrator — logs in once, scrapes both sources, merges, filters), `parse_homework_entry(raw: dict) -> dict` (now requires a parseable `deadline`, returns it as an ISO string), `today_weekday_index(today: date) -> int`, `KretaClientError`. Internal (still importable for tests): `_login(page, kid)`, `_scrape_orarend(page, kid) -> list[dict]`, `_scrape_haza_feladatok(page, kid) -> list[dict]`, `_parse_hun_date(raw: str) -> date`, `_merge_homework_entries(entries: list[dict]) -> list[dict]`, `_filter_upcoming(entries: list[dict], today: date) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

Replace `ekreta-scraper/tests/test_kreta_client.py` entirely with:

```python
from datetime import date

import kreta_client
import pytest
from config import Kid
from kreta_client import (
    KretaClientError,
    fetch_homework,
    parse_homework_entry,
    today_weekday_index,
)


def make_kid() -> Kid:
    return Kid(
        child_id="child1", username="u", password="p", institution_code="035120"
    )


def test_today_weekday_index_monday():
    assert today_weekday_index(date(2026, 9, 7)) == 0  # Monday


def test_today_weekday_index_friday():
    assert today_weekday_index(date(2026, 9, 11)) == 4  # Friday


def test_today_weekday_index_saturday_raises():
    with pytest.raises(KretaClientError):
        today_weekday_index(date(2026, 9, 12))  # Saturday


def test_parse_homework_entry_full():
    raw = {
        "subject": " Matematika ",
        "teacher": " Kovács Béla ",
        "deadline": " 2026. 09. 08. ",
        "text": " 23. oldal, 4-5. feladat ",
        "attachments": ["worksheet.pdf"],
    }
    assert parse_homework_entry(raw) == {
        "subject": "Matematika",
        "teacher": "Kovács Béla",
        "deadline": "2026-09-08",
        "text": "23. oldal, 4-5. feladat",
        "attachments": ["worksheet.pdf"],
    }


def test_parse_homework_entry_missing_attachments_defaults_empty():
    raw = {
        "subject": "Matek",
        "teacher": "X",
        "deadline": "2026. 09. 08.",
        "text": "p.23",
    }
    assert parse_homework_entry(raw)["attachments"] == []


def test_parse_homework_entry_raises_on_unparseable_deadline():
    raw = {"subject": "Matek", "teacher": "X", "deadline": "not a date", "text": ""}
    with pytest.raises(KretaClientError):
        parse_homework_entry(raw)


class TestParseHunDate:
    def test_dotted_with_spaces(self):
        assert kreta_client._parse_hun_date("2026. 09. 08.") == date(2026, 9, 8)

    def test_dotted_no_spaces(self):
        assert kreta_client._parse_hun_date("2026.09.08.") == date(2026, 9, 8)

    def test_iso_fallback(self):
        assert kreta_client._parse_hun_date("2026-09-08") == date(2026, 9, 8)

    def test_raises_on_garbage(self):
        with pytest.raises(KretaClientError):
            kreta_client._parse_hun_date("nem dátum")


class TestMergeHomeworkEntries:
    def test_same_key_collapses_and_keeps_richer_text(self):
        entries = [
            {
                "subject": "Matek",
                "teacher": "",
                "deadline": "2026-09-10",
                "text": "short",
                "attachments": ["a.pdf"],
            },
            {
                "subject": "Matek",
                "teacher": "Kovács Béla",
                "deadline": "2026-09-10",
                "text": "much longer description",
                "attachments": ["b.pdf"],
            },
        ]
        merged = kreta_client._merge_homework_entries(entries)
        assert len(merged) == 1
        assert merged[0]["text"] == "much longer description"
        assert merged[0]["teacher"] == "Kovács Béla"
        assert merged[0]["attachments"] == ["a.pdf", "b.pdf"]

    def test_different_subject_or_deadline_stays_separate(self):
        entries = [
            {
                "subject": "Matek",
                "teacher": "",
                "deadline": "2026-09-10",
                "text": "a",
                "attachments": [],
            },
            {
                "subject": "Angol",
                "teacher": "",
                "deadline": "2026-09-10",
                "text": "b",
                "attachments": [],
            },
            {
                "subject": "Matek",
                "teacher": "",
                "deadline": "2026-09-11",
                "text": "c",
                "attachments": [],
            },
        ]
        merged = kreta_client._merge_homework_entries(entries)
        assert len(merged) == 3


class TestFilterUpcoming:
    def test_drops_past_deadlines_keeps_today_and_future(self):
        entries = [
            {"subject": "Past", "deadline": "2026-09-07"},
            {"subject": "Today", "deadline": "2026-09-08"},
            {"subject": "Future", "deadline": "2026-09-09"},
        ]
        result = kreta_client._filter_upcoming(entries, date(2026, 9, 8))
        assert [e["subject"] for e in result] == ["Today", "Future"]


class TestFetchHomeworkOrchestration:
    def test_merges_both_sources_and_filters(self, monkeypatch):
        monkeypatch.setattr(kreta_client, "_login", lambda page, kid: None)
        monkeypatch.setattr(
            kreta_client,
            "_scrape_orarend",
            lambda page, kid: [
                {
                    "subject": "Matek",
                    "teacher": "",
                    "deadline": "2026-09-10",
                    "text": "a",
                    "attachments": [],
                }
            ],
        )
        monkeypatch.setattr(
            kreta_client,
            "_scrape_haza_feladatok",
            lambda page, kid: [
                {
                    "subject": "Angol",
                    "teacher": "",
                    "deadline": "2026-09-01",
                    "text": "expired",
                    "attachments": [],
                }
            ],
        )
        monkeypatch.setattr(kreta_client, "date", _FixedDate)
        result = fetch_homework(page=None, kid=make_kid())
        assert [e["subject"] for e in result] == ["Matek"]

    def test_one_source_failing_does_not_drop_the_other(self, monkeypatch):
        monkeypatch.setattr(kreta_client, "_login", lambda page, kid: None)

        def raising_orarend(page, kid):
            raise RuntimeError("weekend / no orarend view")

        monkeypatch.setattr(kreta_client, "_scrape_orarend", raising_orarend)
        monkeypatch.setattr(
            kreta_client,
            "_scrape_haza_feladatok",
            lambda page, kid: [
                {
                    "subject": "Angol",
                    "teacher": "",
                    "deadline": "2026-09-10",
                    "text": "still works",
                    "attachments": [],
                }
            ],
        )
        monkeypatch.setattr(kreta_client, "date", _FixedDate)
        result = fetch_homework(page=None, kid=make_kid())
        assert [e["subject"] for e in result] == ["Angol"]


class _FixedDate(date):
    @classmethod
    def today(cls):
        return date(2026, 9, 8)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ekreta-scraper && python -m pytest tests/test_kreta_client.py -v`
Expected: FAIL — `parse_homework_entry`'s current implementation doesn't parse dates (returns the deadline unchanged, so the Hungarian-format assertions fail), `_parse_hun_date`/`_merge_homework_entries`/`_filter_upcoming`/`_login`/`_scrape_orarend`/`_scrape_haza_feladatok` don't exist yet (`AttributeError`).

- [ ] **Step 3: Rewrite the implementation**

Replace `ekreta-scraper/src/kreta_client.py` entirely with:

```python
import sys
from datetime import date, datetime

from config import Kid

INSTITUTION_SEARCH_URL = "https://intezmenykereso.e-kreta.hu/"

_HAZA_FELADATOK_DEADLINE_HEADER = "Házi feladat határideje"
_HUN_DATE_FORMATS = ("%Y. %m. %d.", "%Y.%m.%d.", "%Y-%m-%d")


class KretaClientError(Exception):
    """Raised when scraping fails for a kid (login, navigation, or no school that day)."""


def today_weekday_index(today: date) -> int:
    """Monday=0 .. Friday=4, matching Órarend's fixed 5-column week layout."""
    weekday = today.weekday()
    if weekday > 4:
        raise KretaClientError(f"No school on weekday index {weekday} (weekend)")
    return weekday


def _parse_hun_date(raw: str) -> date:
    """Parse a Hungarian-locale eKRÉTA date string into a date.

    Tries the format seen on Órarend's dialog footer ("2026. 09. 09."), a
    plausible Házi Feladatok list-page format without spaces
    ("2026.09.09."), and plain ISO as a fallback.
    """
    text = raw.strip()
    for fmt in _HUN_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise KretaClientError(f"Unparseable deadline date: {raw!r}")


def parse_homework_entry(raw: dict) -> dict:
    """Normalize a raw scraped homework dict into the spec's entry shape."""
    deadline = _parse_hun_date(raw.get("deadline", ""))
    return {
        "subject": raw.get("subject", "").strip(),
        "teacher": raw.get("teacher", "").strip(),
        "deadline": deadline.isoformat(),
        "text": raw.get("text", "").strip(),
        "attachments": raw.get("attachments") or [],
    }


def _merge_homework_entries(entries: list[dict]) -> list[dict]:
    """Collapse same-(subject, deadline) entries from both sources into one.

    Keeps the richer `text`, unions `attachments`, fills in `teacher` from
    whichever entry has one.
    """
    merged: dict[tuple[str, str], dict] = {}
    for entry in entries:
        key = (entry["subject"], entry["deadline"])
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(entry)
            continue
        if len(entry["text"]) > len(existing["text"]):
            existing["text"] = entry["text"]
        if not existing["teacher"]:
            existing["teacher"] = entry["teacher"]
        existing["attachments"] = sorted(
            set(existing["attachments"]) | set(entry["attachments"])
        )
    return list(merged.values())


def _filter_upcoming(entries: list[dict], today: date) -> list[dict]:
    """Keep only entries whose deadline hasn't passed yet."""
    return [e for e in entries if date.fromisoformat(e["deadline"]) >= today]


def _login(page, kid: Kid) -> None:
    """Institution search + credential login, shared by both scrape sources."""
    page.goto(INSTITUTION_SEARCH_URL, wait_until="networkidle")
    page.locator("#institute-selector-auto-complete-input-id").fill(
        kid.institution_code
    )
    page.locator("li").first.wait_for()
    page.locator("li").first.click()
    page.get_by_role("button", name="TOVÁBB A KRÉTA OLDALÁRA").click()
    page.wait_for_load_state("networkidle")

    page.locator("#UserName").fill(kid.username)
    page.locator("#Password").fill(kid.password)
    page.get_by_role("button", name="Bejelentkezés").click()
    page.wait_for_load_state("networkidle")


def _scrape_orarend(page, kid: Kid) -> list[dict]:
    """Scrape today's homework-icon lessons off the Órarend week view.

    Selectors confirmed against the live site (2026-09-08, Brassó Utcai
    Általános Iskola / 035120): Órarend is a FullCalendar week view where
    each weekday is a single `<td>` containing one `.fc-event-container`
    with one `<a class="fc-time-grid-event">` per lesson period that day; a
    lesson with homework carries an `i.hasCalendarIcon` (house) icon inside
    it. Clicking a lesson opens a Kendo UI modal dialog with two tabs,
    "Óra adatai" (lesson data) and "Házi feladat" (homework) — both tab
    panels exist in the DOM at once, only their visibility toggles, so
    fields from either tab can be read regardless of which tab is currently
    showing.
    """
    weekday_index = today_weekday_index(date.today())

    page.get_by_text("Elektronikus ellenőrzőkönyv").click()
    page.wait_for_load_state("networkidle")
    page.get_by_text("Órarend", exact=True).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("td:has(.fc-event-container)")

    event_columns = page.locator("td:has(.fc-event-container)")
    if event_columns.count() <= weekday_index:
        # No week grid rendered for today (e.g. holiday view) — nothing due.
        return []
    today_column = event_columns.nth(weekday_index)
    house_lessons = today_column.locator("a.fc-time-grid-event:has(i.hasCalendarIcon)")

    entries: list[dict] = []
    for i in range(house_lessons.count()):
        house_lessons.nth(i).click()
        page.wait_for_selector("[role=dialog]")
        # The dialog's Kendo TabStrip widget needs a moment to finish
        # binding its click handlers after the dialog DOM appears —
        # clicking the tab immediately on dialog-open is a no-op.
        page.wait_for_timeout(500)
        page.get_by_text("Házi feladat", exact=True).first.click()
        page.wait_for_selector(".panel-body")

        raw = {
            "subject": page.locator('[displayfor="Targy"]').inner_text(),
            "teacher": page.locator('[displayfor="Tanar"]').inner_text(),
            "deadline": page.locator(".panel-footer")
            .first.inner_text()
            .replace("Határidő:", ""),
            "text": page.locator(".panel-body").first.inner_text(),
            "attachments": [
                row.locator("td").first.inner_text()
                for row in page.locator(
                    "#HFCsatolmanyGrid tbody tr:not(.k-no-data)"
                ).all()
            ],
        }
        try:
            entries.append(parse_homework_entry(raw))
        except KretaClientError as exc:
            print(  # noqa: T201
                f"[WARN] skipping unparseable orarend lesson for {kid.child_id}: {exc}",
                file=sys.stderr,
            )

        page.locator("#BtnCancel").click()
        page.wait_for_timeout(300)

    return entries


def _column_index(header_cells, header_text: str) -> int | None:
    """Find a table column's index by its header text."""
    for i, cell in enumerate(header_cells):
        if cell.inner_text().strip() == header_text:
            return i
    return None


def _scrape_haza_feladatok(page, kid: Kid) -> list[dict]:
    """Scrape the Tanulo/TanuloHaziFeladat homework list table.

    Unlike Órarend's selectors (confirmed against the live site above),
    this page has not been inspected live — selectors here are a
    best-effort guess and must be verified against the real site (or a
    saved HTML sample) before this ships. The deadline column is located
    by its known header text rather than a hardcoded index, to survive
    column-order differences from whatever the real markup turns out to
    be; other columns fall back to empty values if not found.
    """
    page.get_by_text("Elektronikus ellenőrzőkönyv").click()
    page.wait_for_load_state("networkidle")
    page.get_by_text("Házi feladatok", exact=True).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("table tbody tr")

    header_cells = page.locator("table thead th").all()
    subject_idx = _column_index(header_cells, "Tantárgy")
    deadline_idx = _column_index(header_cells, _HAZA_FELADATOK_DEADLINE_HEADER)
    text_idx = _column_index(header_cells, "Feladat leírása")
    teacher_idx = _column_index(header_cells, "Tanár")
    if deadline_idx is None or subject_idx is None:
        raise KretaClientError("Házi feladatok table missing expected columns")

    entries: list[dict] = []
    for row in page.locator("table tbody tr").all():
        cells = row.locator("td").all()
        raw = {
            "subject": cells[subject_idx].inner_text(),
            "teacher": cells[teacher_idx].inner_text() if teacher_idx is not None else "",
            "deadline": cells[deadline_idx].inner_text(),
            "text": cells[text_idx].inner_text() if text_idx is not None else "",
            "attachments": [],
        }
        try:
            entries.append(parse_homework_entry(raw))
        except KretaClientError as exc:
            print(  # noqa: T201
                f"[WARN] skipping unparseable haza_feladatok row for "
                f"{kid.child_id}: {exc}",
                file=sys.stderr,
            )

    return entries


def fetch_homework(page, kid: Kid) -> list[dict]:
    """Full login-to-scrape flow for one kid, merging both homework sources.

    Logs in once, then scrapes Órarend and Házi Feladatok independently —
    one source failing (nav error, markup change, weekend with no Órarend
    view) does not drop the other source's results. Same-(subject,
    deadline) entries from both sources are merged into one; the result is
    filtered to not-yet-due items before being returned for posting.
    """
    _login(page, kid)

    entries: list[dict] = []
    try:
        entries += _scrape_orarend(page, kid)
    except Exception as exc:
        print(  # noqa: T201
            f"[WARN] orarend scrape failed for {kid.child_id}: {exc}", file=sys.stderr
        )
    try:
        entries += _scrape_haza_feladatok(page, kid)
    except Exception as exc:
        print(  # noqa: T201
            f"[WARN] haza_feladatok scrape failed for {kid.child_id}: {exc}",
            file=sys.stderr,
        )

    merged = _merge_homework_entries(entries)
    return _filter_upcoming(merged, date.today())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ekreta-scraper && python -m pytest tests/test_kreta_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ekreta-scraper/src/kreta_client.py ekreta-scraper/tests/test_kreta_client.py
git commit -m "feat: scrape homework from Órarend + Házi Feladatok, merge and filter

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: `api_client.post_homework` — drop the `day` parameter

**Files:**
- Modify: `ekreta-scraper/src/api_client.py`
- Test: `ekreta-scraper/tests/test_api_client.py`

**Interfaces:**
- Consumes: nothing project-local (plain `httpx`).
- Produces: `post_homework(api_url: str, token: str, child_id: str, entries: list[dict]) -> None`.

- [ ] **Step 1: Write the failing tests**

Replace `ekreta-scraper/tests/test_api_client.py` entirely with:

```python
"""Tests for the api_client module."""

import httpx
import pytest
from api_client import post_homework


def test_post_homework_sends_expected_payload(monkeypatch):
    """Test that post_homework sends expected payload."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured['url'] = url
        captured['headers'] = headers
        captured['json'] = json
        return httpx.Response(204, request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx, 'post', fake_post)
    post_homework(
        'http://familylink-web:8000',
        'secret-token',
        'child1',
        [{'subject': 'Matek'}],
    )
    assert captured['url'] == 'http://familylink-web:8000/internal/ekreta/homework'
    assert captured['headers'] == {'X-Api-Key': 'secret-token'}
    assert captured['json'] == {
        'child_id': 'child1',
        'entries': [{'subject': 'Matek'}],
    }


def test_post_homework_raises_on_http_error(monkeypatch):
    """Test that post_homework raises on HTTP error status."""

    def fake_post(url, headers=None, json=None, timeout=None):
        return httpx.Response(401, request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx, 'post', fake_post)
    with pytest.raises(httpx.HTTPStatusError):
        post_homework('http://familylink-web:8000', 'bad', 'child1', [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ekreta-scraper && python -m pytest tests/test_api_client.py -v`
Expected: FAIL — `TypeError: post_homework() missing 1 required positional argument` (old signature still takes `day`).

- [ ] **Step 3: Update the implementation**

Replace `ekreta-scraper/src/api_client.py` entirely with:

```python
"""Posts scraped homework results back to familylink-server."""

import httpx


def post_homework(
    api_url: str, token: str, child_id: str, entries: list[dict]
) -> None:
    """POST one kid's scraped, not-yet-due homework to familylink-server."""
    resp = httpx.post(
        f'{api_url}/internal/ekreta/homework',
        headers={'X-Api-Key': token},
        json={'child_id': child_id, 'entries': entries},
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
git commit -m "feat: drop day param from post_homework (entries carry deadline)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 9: `main.py` — `run()` no longer threads `today`/`day` to `post_fn`

**Files:**
- Modify: `ekreta-scraper/src/main.py`
- Test: `ekreta-scraper/tests/test_main.py`

**Interfaces:**
- Consumes: `Kid`, `fetch_kids` (`config.py`, unchanged); `post_homework(api_url, token, child_id, entries)` (Task 8); `fetch_homework(page, kid)` (Task 7).
- Produces: `run(kids: list[Kid], api_url: str, token: str, fetch_fn, post_fn=post_homework) -> int` (`0` if every kid succeeded, `1` if any failed); `main() -> int`.

- [ ] **Step 1: Write the failing tests**

Replace `ekreta-scraper/tests/test_main.py` entirely with:

```python
"""Tests for the main module's run() and main() functions."""

from config import Kid
from main import run


def make_kid(child_id: str) -> Kid:
    """Create a fake Kid for testing."""
    return Kid(
        child_id=child_id,
        username=f'{child_id}-user',
        password='pw',
        institution_code='035120',
    )


def test_run_posts_entries_for_each_kid():
    """Test that run() calls post_fn for each kid with correct args."""
    kids = [make_kid('child1'), make_kid('child2')]
    fake_entries = {'child1': [{'subject': 'Matek'}], 'child2': []}
    posted = []

    def fake_post(api_url, token, child_id, entries):
        posted.append((api_url, token, child_id, entries))

    exit_code = run(
        kids=kids,
        api_url='http://familylink-web:8000',
        token='secret',
        fetch_fn=lambda kid: fake_entries[kid.child_id],
        post_fn=fake_post,
    )

    assert exit_code == 0
    assert posted == [
        (
            'http://familylink-web:8000',
            'secret',
            'child1',
            [{'subject': 'Matek'}],
        ),
        ('http://familylink-web:8000', 'secret', 'child2', []),
    ]


def test_run_continues_after_one_kid_fails():
    """Test that run() continues processing after one kid's fetch fails."""
    kids = [make_kid('child1'), make_kid('child2')]
    posted = []

    def fetch_fn(kid):
        if kid.child_id == 'child1':
            raise RuntimeError('login failed')
        return []

    exit_code = run(
        kids=kids,
        api_url='http://familylink-web:8000',
        token='secret',
        fetch_fn=fetch_fn,
        post_fn=lambda *args: posted.append(args),
    )

    assert exit_code == 1
    assert len(posted) == 1
    assert posted[0][2] == 'child2'


def test_run_continues_after_one_kid_post_fails():
    """Test that run() continues processing after one kid's post_fn fails."""
    kids = [make_kid('child1'), make_kid('child2')]
    posted = []

    def post_fn(api_url, token, child_id, entries):
        if child_id == 'child1':
            raise RuntimeError('API unreachable')
        posted.append((api_url, token, child_id, entries))

    exit_code = run(
        kids=kids,
        api_url='http://familylink-web:8000',
        token='secret',
        fetch_fn=lambda kid: [],
        post_fn=post_fn,
    )

    assert exit_code == 1
    assert len(posted) == 1
    assert posted[0][2] == 'child2'


def test_run_all_succeed_returns_zero():
    """Test that run() returns 0 when all kids succeed."""
    kids = [make_kid('child1')]
    exit_code = run(
        kids=kids,
        api_url='http://familylink-web:8000',
        token='secret',
        fetch_fn=lambda kid: [],
        post_fn=lambda *args: None,
    )
    assert exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ekreta-scraper && python -m pytest tests/test_main.py -v`
Expected: FAIL — `TypeError` from the old `run()`/`post_fn` signature still expecting a `today`/`day` argument.

- [ ] **Step 3: Update the implementation**

Replace `ekreta-scraper/src/main.py` entirely with:

```python
"""Wire together config, api_client, and kreta_client to scrape and post homework."""

import sys
from collections.abc import Callable

from api_client import post_homework
from config import Kid, fetch_kids


def run(
    kids: list[Kid],
    api_url: str,
    token: str,
    fetch_fn: Callable[[Kid], list[dict]],
    post_fn: Callable[[str, str, str, list[dict]], None] = post_homework,
) -> int:
    """Scrape homework for each kid and POST to the API.

    On failure for any kid, log to stderr and skip posting for that kid,
    returning 1 to signal partial failure.
    """
    any_failed = False

    for kid in kids:
        try:
            entries = fetch_fn(kid)
        except Exception as exc:
            print(f'[ERROR] {kid.child_id}: {exc}', file=sys.stderr)  # noqa: T201
            any_failed = True
            continue

        try:
            post_fn(api_url, token, kid.child_id, entries)
        except Exception as exc:
            print(f'[ERROR] {kid.child_id}: {exc}', file=sys.stderr)  # noqa: T201
            any_failed = True
            continue

    return 1 if any_failed else 0


def main() -> int:
    """Launch browser, fetch homework for all kids, and post results to API."""
    import os

    from kreta_client import fetch_homework
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    api_url = os.environ['FAMILYLINK_API_URL']
    token = os.environ['EKRETA_INGEST_TOKEN']
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


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ekreta-scraper && python -m pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Confirm full suites still pass**

Run: `python -m pytest` (from repo root) and `cd ekreta-scraper && python -m pytest`
Expected: PASS on both

- [ ] **Step 6: Commit**

```bash
git add ekreta-scraper/src/main.py ekreta-scraper/tests/test_main.py
git commit -m "feat: drop day threading from run()/post_fn now entries carry deadline

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
