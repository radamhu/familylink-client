# Linux Machine Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SSH-based screen-time enforcement for Linux machines: register machines in the web UI, poll them every 60 s, soft-lock the session when the daily limit is exhausted, and power off after a grace period.

**Architecture:** A background asyncio task (`linux_poller.py`) mirrors the existing Discord bot pattern in `lifespan`. It reads registered machines from two new DB tables (`linux_machines`, `linux_usage_snapshots`), SSHes in with `asyncssh`, accumulates active-session seconds, and calls `loginctl lock-sessions` / `systemctl poweroff` at the right thresholds. A new FastAPI router handles CRUD and manual lock/poweroff; Jinja2 + HTMX templates follow the existing device-card pattern.

**Tech Stack:** `asyncssh>=2.14`, SQLAlchemy async ORM (already in use), Alembic (already in use), FastAPI + Jinja2 + HTMX (already in use), pytest + pytest-mock (already in use).

## Global Constraints

- Python 3.12 (pyenv `.python-version`). Run `python -m pytest`, never `uv run pytest`.
- Single-quoted inline strings, Google docstring style — enforced by ruff.
- `asyncio_mode = "auto"` in `pytest.ini` — all `async def test_*` run automatically.
- All server tests set env vars in `tests/server/conftest.py` before importing app modules.
- Install: `pip install -e ".[dev,test,server]"`.

---

## File Map

| Action | Path |
|---|---|
| Modify | `pyproject.toml` — add `asyncssh>=2.14` to `[server]` extras |
| Modify | `src/familylink_server/db/models.py` — add `LinuxMachine`, `LinuxUsageSnapshot` |
| Modify | `src/familylink_server/db/session.py` — add `make_session` context manager |
| Modify | `src/familylink_server/db/__init__.py` — export new models + `make_session` |
| Create | `alembic/versions/002_linux_machines.py` — migration for two new tables |
| Create | `src/familylink_server/services/linux_ssh.py` — SSH helpers |
| Create | `src/familylink_server/services/linux_poller.py` — background poll loop |
| Create | `src/familylink_server/routers/linux_machines.py` — CRUD + action endpoints |
| Create | `src/familylink_server/templates/linux_machines.html` — full page |
| Create | `src/familylink_server/templates/linux_machine_form.html` — add/edit form |
| Create | `src/familylink_server/templates/partials/linux_machine_card.html` — HTMX swap target |
| Modify | `src/familylink_server/templates/base.html` — add nav link |
| Modify | `src/familylink_server/main.py` — wire poller + router into lifespan |
| Create | `tests/server/test_linux_ssh.py` |
| Create | `tests/server/test_linux_poller.py` |
| Create | `tests/server/test_routers_linux_machines.py` |

---

## Task 1: Dependency + DB models + migration

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/familylink_server/db/models.py`
- Modify: `src/familylink_server/db/session.py`
- Modify: `src/familylink_server/db/__init__.py`
- Create: `alembic/versions/002_linux_machines.py`
- Test: `tests/server/test_db_models.py` (extend the existing file)

**Interfaces:**
- Produces: `LinuxMachine` ORM model, `LinuxUsageSnapshot` ORM model, `make_session()` async context manager — all imported by later tasks.

- [ ] **Step 1: Add asyncssh to pyproject.toml**

In `pyproject.toml`, add `asyncssh>=2.14` to `[project.optional-dependencies] server`:

```toml
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
    "discord.py>=2.4",
    "asyncssh>=2.14",
]
```

- [ ] **Step 2: Install**

```bash
pip install -e ".[dev,test,server]"
```

Expected: resolves and installs `asyncssh` without errors.

- [ ] **Step 3: Add ORM models**

Append to `src/familylink_server/db/models.py` (after the existing `AuditLog` class):

```python
from sqlalchemy import ForeignKey  # add to existing import line


class LinuxMachine(Base):
    """Registered Linux machine managed via SSH."""

    __tablename__ = 'linux_machines'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False)
    friendly_name: Mapped[str] = mapped_column(String(256), nullable=False)
    hostname: Mapped[str] = mapped_column(String(256), nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_user: Mapped[str] = mapped_column(String(64), nullable=False)
    ssh_private_key: Mapped[str] = mapped_column(Text, nullable=False)
    daily_limit_mins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grace_period_mins: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LinuxUsageSnapshot(Base):
    """Daily active-session accumulator for a Linux machine."""

    __tablename__ = 'linux_usage_snapshots'
    __table_args__ = (UniqueConstraint('machine_id', 'date'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('linux_machines.id', ondelete='CASCADE'), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    active_seconds: Mapped[int] = mapped_column(Integer, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    poweroff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

The full import line at the top of `models.py` should become:

```python
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
```

- [ ] **Step 4: Add make_session to session.py**

Add to `src/familylink_server/db/session.py` after the `get_session` function:

```python
from contextlib import asynccontextmanager


@asynccontextmanager
async def make_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for use outside FastAPI dependency injection.

    Use in background tasks and scripts:
        async with make_session() as session:
            ...
    """
    async with _session_factory() as session:
        yield session
```

The `AsyncGenerator` import is already present from `from collections.abc import AsyncGenerator`.

- [ ] **Step 5: Export new symbols from db/__init__.py**

Replace the contents of `src/familylink_server/db/__init__.py`:

```python
"""Database models and session factory for Family Link server."""

from familylink_server.db.models import (
    AppConfig,
    AuditLog,
    Base,
    DeviceSnapshot,
    LinuxMachine,
    LinuxUsageSnapshot,
    UsageSnapshot,
)
from familylink_server.db.session import get_session, make_session

__all__ = [
    'AppConfig',
    'AuditLog',
    'Base',
    'DeviceSnapshot',
    'LinuxMachine',
    'LinuxUsageSnapshot',
    'UsageSnapshot',
    'get_session',
    'make_session',
]
```

- [ ] **Step 6: Write failing model test**

Add to `tests/server/test_db_models.py`:

```python
def test_linux_machine_model_attributes():
    """LinuxMachine has expected columns with correct defaults."""
    from familylink_server.db.models import LinuxMachine
    m = LinuxMachine(
        child_id='child1',
        friendly_name='Gaming PC',
        hostname='192.168.1.10',
        ssh_user='kid',
        ssh_private_key='-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----',
        created_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
    )
    assert m.ssh_port == 22
    assert m.grace_period_mins == 5
    assert m.enabled is True
    assert m.daily_limit_mins is None


def test_linux_usage_snapshot_model_attributes():
    """LinuxUsageSnapshot has expected columns."""
    from familylink_server.db.models import LinuxUsageSnapshot
    snap = LinuxUsageSnapshot(
        machine_id=1,
        date=__import__('datetime').date.today(),
        active_seconds=120,
        updated_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
    )
    assert snap.locked_at is None
    assert snap.poweroff_at is None
```

- [ ] **Step 7: Run test — expect pass (pure model instantiation, no DB)**

```bash
python -m pytest tests/server/test_db_models.py::test_linux_machine_model_attributes tests/server/test_db_models.py::test_linux_usage_snapshot_model_attributes -v
```

Expected: both PASS.

- [ ] **Step 8: Create Alembic migration**

Create `alembic/versions/002_linux_machines.py`:

```python
"""add linux_machines and linux_usage_snapshots tables

Revision ID: 002
Revises: 001
Create Date: 2026-06-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '002'
down_revision: str | Sequence[str] | None = '001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add linux_machines and linux_usage_snapshots."""
    op.create_table(
        'linux_machines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('child_id', sa.String(64), nullable=False),
        sa.Column('friendly_name', sa.String(256), nullable=False),
        sa.Column('hostname', sa.String(256), nullable=False),
        sa.Column('ssh_port', sa.Integer(), nullable=False, server_default='22'),
        sa.Column('ssh_user', sa.String(64), nullable=False),
        sa.Column('ssh_private_key', sa.Text(), nullable=False),
        sa.Column('daily_limit_mins', sa.Integer(), nullable=True),
        sa.Column('grace_period_mins', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'linux_usage_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('machine_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('active_seconds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('poweroff_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['machine_id'], ['linux_machines.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('machine_id', 'date'),
    )


def downgrade() -> None:
    """Drop linux_machines and linux_usage_snapshots."""
    op.drop_table('linux_usage_snapshots')
    op.drop_table('linux_machines')
```

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml \
        src/familylink_server/db/models.py \
        src/familylink_server/db/session.py \
        src/familylink_server/db/__init__.py \
        alembic/versions/002_linux_machines.py \
        tests/server/test_db_models.py
git commit -m "feat: add LinuxMachine and LinuxUsageSnapshot models with migration"
```

---

## Task 2: SSH helpers

**Files:**
- Create: `src/familylink_server/services/linux_ssh.py`
- Create: `tests/server/test_linux_ssh.py`

**Interfaces:**
- Produces:
  - `check_session(hostname: str, port: int, user: str, key_text: str) -> bool`
  - `lock_session(hostname: str, port: int, user: str, key_text: str) -> None`
  - `poweroff_machine(hostname: str, port: int, user: str, key_text: str) -> None`
- Consumed by: `linux_poller.py` (Task 3), `routers/linux_machines.py` (Task 4).

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_linux_ssh.py`:

```python
"""Tests for SSH helpers in linux_ssh.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_ssh_mock(stdout: str) -> tuple:
    """Return (mock_conn, mock_context_manager) for asyncssh.connect."""
    mock_result = MagicMock(stdout=stdout, exit_status=0)
    mock_conn = MagicMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_conn, mock_cm


async def test_check_session_returns_true_when_active():
    """check_session returns True when loginctl output contains 'active'."""
    from familylink_server.services.linux_ssh import check_session

    _, mock_cm = _make_ssh_mock('5 1000 user seat0 :0 active')
    with (
        patch('familylink_server.services.linux_ssh.asyncssh.import_private_key', return_value=MagicMock()),
        patch('familylink_server.services.linux_ssh.asyncssh.connect', return_value=mock_cm),
    ):
        result = await check_session('host', 22, 'user', 'fake-pem')
    assert result is True


async def test_check_session_falls_back_to_who():
    """check_session falls back to 'who' if loginctl has no 'active'."""
    from familylink_server.services.linux_ssh import check_session

    mock_result_loginctl = MagicMock(stdout='no sessions', exit_status=0)
    mock_result_who = MagicMock(stdout='kid  tty7  2026-06-25 10:00 (:0)', exit_status=0)
    mock_conn = MagicMock()
    mock_conn.run = AsyncMock(side_effect=[mock_result_loginctl, mock_result_who])
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch('familylink_server.services.linux_ssh.asyncssh.import_private_key', return_value=MagicMock()),
        patch('familylink_server.services.linux_ssh.asyncssh.connect', return_value=mock_cm),
    ):
        result = await check_session('host', 22, 'user', 'fake-pem')
    assert result is True


async def test_check_session_returns_false_when_no_session():
    """check_session returns False when both loginctl and who show no session."""
    from familylink_server.services.linux_ssh import check_session

    mock_result = MagicMock(stdout='', exit_status=0)
    mock_conn = MagicMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch('familylink_server.services.linux_ssh.asyncssh.import_private_key', return_value=MagicMock()),
        patch('familylink_server.services.linux_ssh.asyncssh.connect', return_value=mock_cm),
    ):
        result = await check_session('host', 22, 'user', 'fake-pem')
    assert result is False


async def test_lock_session_runs_loginctl():
    """lock_session issues loginctl lock-sessions over SSH."""
    from familylink_server.services.linux_ssh import lock_session

    mock_conn, mock_cm = _make_ssh_mock('')
    with (
        patch('familylink_server.services.linux_ssh.asyncssh.import_private_key', return_value=MagicMock()),
        patch('familylink_server.services.linux_ssh.asyncssh.connect', return_value=mock_cm),
    ):
        await lock_session('host', 22, 'user', 'fake-pem')
    mock_conn.run.assert_awaited_once_with('loginctl lock-sessions', check=False)


async def test_poweroff_machine_runs_systemctl():
    """poweroff_machine issues systemctl poweroff over SSH."""
    from familylink_server.services.linux_ssh import poweroff_machine

    mock_conn, mock_cm = _make_ssh_mock('')
    with (
        patch('familylink_server.services.linux_ssh.asyncssh.import_private_key', return_value=MagicMock()),
        patch('familylink_server.services.linux_ssh.asyncssh.connect', return_value=mock_cm),
    ):
        await poweroff_machine('host', 22, 'user', 'fake-pem')
    mock_conn.run.assert_awaited_once_with('systemctl poweroff', check=False)
```

- [ ] **Step 2: Run tests — expect ImportError/ModuleNotFoundError**

```bash
python -m pytest tests/server/test_linux_ssh.py -v
```

Expected: FAIL — `cannot import name 'check_session' from 'familylink_server.services.linux_ssh'`.

- [ ] **Step 3: Implement linux_ssh.py**

Create `src/familylink_server/services/linux_ssh.py`:

```python
"""SSH helpers for Linux machine control."""

import asyncssh


async def check_session(hostname: str, port: int, user: str, key_text: str) -> bool:
    """Return True if a user session is currently active on the machine."""
    key = asyncssh.import_private_key(key_text)
    async with asyncssh.connect(
        hostname,
        port=port,
        username=user,
        client_keys=[key],
        known_hosts=None,
        connect_timeout=10,
    ) as conn:
        result = await conn.run('loginctl list-sessions --no-pager', check=False)
        if 'active' in result.stdout:
            return True
        result2 = await conn.run('who', check=False)
        return bool(result2.stdout.strip())


async def lock_session(hostname: str, port: int, user: str, key_text: str) -> None:
    """Lock all active sessions on the machine."""
    key = asyncssh.import_private_key(key_text)
    async with asyncssh.connect(
        hostname,
        port=port,
        username=user,
        client_keys=[key],
        known_hosts=None,
        connect_timeout=10,
    ) as conn:
        await conn.run('loginctl lock-sessions', check=False)


async def poweroff_machine(hostname: str, port: int, user: str, key_text: str) -> None:
    """Power off the machine immediately."""
    key = asyncssh.import_private_key(key_text)
    async with asyncssh.connect(
        hostname,
        port=port,
        username=user,
        client_keys=[key],
        known_hosts=None,
        connect_timeout=10,
    ) as conn:
        await conn.run('systemctl poweroff', check=False)
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
python -m pytest tests/server/test_linux_ssh.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/services/linux_ssh.py tests/server/test_linux_ssh.py
git commit -m "feat: add SSH helpers for Linux machine control"
```

---

## Task 3: Background poller

**Files:**
- Create: `src/familylink_server/services/linux_poller.py`
- Create: `tests/server/test_linux_poller.py`

**Interfaces:**
- Consumes:
  - `check_session(hostname, port, user, key_text) -> bool` (from Task 2)
  - `lock_session(hostname, port, user, key_text) -> None` (from Task 2)
  - `poweroff_machine(hostname, port, user, key_text) -> None` (from Task 2)
  - `LinuxMachine`, `LinuxUsageSnapshot` (from Task 1)
  - `make_session()` (from Task 1)
- Produces:
  - `poll_machine(machine: LinuxMachine) -> None`
  - `poller_loop() -> None` (runs forever; used as asyncio task in `lifespan`)

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_linux_poller.py`:

```python
"""Tests for the Linux machine poller."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_machine(
    machine_id: int = 1,
    daily_limit_mins: int | None = 60,
    grace_period_mins: int = 5,
    hostname: str = 'host',
    ssh_port: int = 22,
    ssh_user: str = 'user',
    ssh_private_key: str = 'key',
    friendly_name: str = 'Test PC',
) -> MagicMock:
    m = MagicMock()
    m.id = machine_id
    m.hostname = hostname
    m.ssh_port = ssh_port
    m.ssh_user = ssh_user
    m.ssh_private_key = ssh_private_key
    m.friendly_name = friendly_name
    m.daily_limit_mins = daily_limit_mins
    m.grace_period_mins = grace_period_mins
    return m


def _make_snapshot(
    active_seconds: int = 0,
    locked_at: datetime.datetime | None = None,
    poweroff_at: datetime.datetime | None = None,
) -> MagicMock:
    snap = MagicMock()
    snap.active_seconds = active_seconds
    snap.locked_at = locked_at
    snap.poweroff_at = poweroff_at
    snap.updated_at = None
    return snap


def _make_session_ctx(snapshot: MagicMock | None) -> MagicMock:
    """Build a mock async context manager that returns snapshot from scalar_one_or_none."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=snapshot))
    )
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx, mock_session


async def test_poll_machine_increments_active_seconds_when_session_active():
    """Active session increments active_seconds by 60."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=None)
    snapshot = _make_snapshot(active_seconds=0)
    mock_ctx, mock_session = _make_session_ctx(snapshot)

    with (
        patch('familylink_server.services.linux_poller.check_session', AsyncMock(return_value=True)),
        patch('familylink_server.services.linux_poller.make_session', return_value=mock_ctx),
    ):
        await poll_machine(machine)

    assert snapshot.active_seconds == 60
    mock_session.commit.assert_awaited_once()


async def test_poll_machine_does_not_increment_when_session_idle():
    """Idle session leaves active_seconds unchanged."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=None)
    snapshot = _make_snapshot(active_seconds=100)
    mock_ctx, mock_session = _make_session_ctx(snapshot)

    with (
        patch('familylink_server.services.linux_poller.check_session', AsyncMock(return_value=False)),
        patch('familylink_server.services.linux_poller.make_session', return_value=mock_ctx),
    ):
        await poll_machine(machine)

    assert snapshot.active_seconds == 100


async def test_poll_machine_applies_soft_lock_when_limit_reached():
    """lock_session is called and locked_at is set when active_seconds >= limit."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)  # 60 s limit
    snapshot = _make_snapshot(active_seconds=60)  # exactly at limit
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_lock = AsyncMock()
    with (
        patch('familylink_server.services.linux_poller.check_session', AsyncMock(return_value=True)),
        patch('familylink_server.services.linux_poller.lock_session', mock_lock),
        patch('familylink_server.services.linux_poller.make_session', return_value=mock_ctx),
    ):
        await poll_machine(machine)

    mock_lock.assert_awaited_once()
    assert snapshot.locked_at is not None


async def test_poll_machine_does_not_relock_when_already_locked():
    """lock_session is NOT called if locked_at is already set."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)
    locked_ts = datetime.datetime.now(datetime.UTC)
    snapshot = _make_snapshot(active_seconds=120, locked_at=locked_ts)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_lock = AsyncMock()
    with (
        patch('familylink_server.services.linux_poller.check_session', AsyncMock(return_value=True)),
        patch('familylink_server.services.linux_poller.lock_session', mock_lock),
        patch('familylink_server.services.linux_poller.poweroff_machine', AsyncMock()),
        patch('familylink_server.services.linux_poller.make_session', return_value=mock_ctx),
    ):
        await poll_machine(machine)

    mock_lock.assert_not_awaited()


async def test_poll_machine_powers_off_after_grace_period():
    """poweroff_machine is called after grace_period_mins have elapsed since locked_at."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1, grace_period_mins=5)
    # locked 6 minutes ago — grace period exceeded
    locked_ts = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=6)
    snapshot = _make_snapshot(active_seconds=120, locked_at=locked_ts)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_poweroff = AsyncMock()
    with (
        patch('familylink_server.services.linux_poller.check_session', AsyncMock(return_value=False)),
        patch('familylink_server.services.linux_poller.poweroff_machine', mock_poweroff),
        patch('familylink_server.services.linux_poller.make_session', return_value=mock_ctx),
    ):
        await poll_machine(machine)

    mock_poweroff.assert_awaited_once()
    assert snapshot.poweroff_at is not None


async def test_poll_machine_skips_when_already_powered_off():
    """No SSH calls after poweroff_at is set for today."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine()
    now = datetime.datetime.now(datetime.UTC)
    snapshot = _make_snapshot(locked_at=now, poweroff_at=now)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_check = AsyncMock(return_value=True)
    with (
        patch('familylink_server.services.linux_poller.check_session', mock_check),
        patch('familylink_server.services.linux_poller.make_session', return_value=mock_ctx),
    ):
        await poll_machine(machine)

    mock_check.assert_awaited_once()  # called to detect active, but then returns early


async def test_poll_machine_logs_warning_on_ssh_failure():
    """SSH failure is caught and logged; no exception propagates."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine()
    with patch(
        'familylink_server.services.linux_poller.check_session',
        AsyncMock(side_effect=ConnectionError('timeout')),
    ):
        await poll_machine(machine)  # must not raise
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
python -m pytest tests/server/test_linux_poller.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement linux_poller.py**

Create `src/familylink_server/services/linux_poller.py`:

```python
"""Background asyncio task that polls Linux machines and enforces screen-time limits."""

import asyncio
import logging
from datetime import UTC, date, datetime

from sqlalchemy import select

from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot
from familylink_server.db.session import make_session
from familylink_server.services.linux_ssh import check_session, lock_session, poweroff_machine

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60


async def poll_machine(machine: LinuxMachine) -> None:
    """Poll one machine: accumulate active seconds and enforce soft/hard limits."""
    today = date.today()

    try:
        active = await check_session(
            machine.hostname, machine.ssh_port, machine.ssh_user, machine.ssh_private_key
        )
    except Exception:
        logger.warning('SSH poll failed for %s', machine.friendly_name)
        return

    async with make_session() as session:
        stmt = select(LinuxUsageSnapshot).where(
            LinuxUsageSnapshot.machine_id == machine.id,
            LinuxUsageSnapshot.date == today,
        )
        snapshot = (await session.execute(stmt)).scalar_one_or_none()

        if snapshot is None:
            snapshot = LinuxUsageSnapshot(
                machine_id=machine.id,
                date=today,
                active_seconds=0,
                updated_at=datetime.now(UTC),
            )
            session.add(snapshot)
            await session.flush()

        if snapshot.poweroff_at is not None:
            return

        if active:
            snapshot.active_seconds += POLL_INTERVAL
            snapshot.updated_at = datetime.now(UTC)

        if (
            machine.daily_limit_mins is not None
            and snapshot.active_seconds >= machine.daily_limit_mins * 60
            and snapshot.locked_at is None
        ):
            try:
                await lock_session(
                    machine.hostname, machine.ssh_port, machine.ssh_user, machine.ssh_private_key
                )
                snapshot.locked_at = datetime.now(UTC)
                logger.info('Soft lock applied to %s', machine.friendly_name)
            except Exception:
                logger.warning('Lock failed for %s', machine.friendly_name)

        if snapshot.locked_at is not None and snapshot.poweroff_at is None:
            elapsed = (datetime.now(UTC) - snapshot.locked_at).total_seconds()
            if elapsed >= machine.grace_period_mins * 60:
                try:
                    await poweroff_machine(
                        machine.hostname, machine.ssh_port, machine.ssh_user, machine.ssh_private_key
                    )
                    snapshot.poweroff_at = datetime.now(UTC)
                    logger.info('Hard poweroff applied to %s', machine.friendly_name)
                except Exception:
                    logger.warning('Poweroff failed for %s', machine.friendly_name)

        await session.commit()


async def poller_loop() -> None:
    """Main poll loop — iterates all enabled machines every POLL_INTERVAL seconds."""
    while True:
        try:
            async with make_session() as session:
                result = await session.execute(
                    select(LinuxMachine).where(LinuxMachine.enabled.is_(True))
                )
                machines = result.scalars().all()

            await asyncio.gather(
                *[poll_machine(m) for m in machines],
                return_exceptions=True,
            )
        except Exception:
            logger.exception('Poller cycle failed')
        await asyncio.sleep(POLL_INTERVAL)
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
python -m pytest tests/server/test_linux_poller.py -v
```

Expected: 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/services/linux_poller.py tests/server/test_linux_poller.py
git commit -m "feat: add Linux machine poller with soft-lock and poweroff enforcement"
```

---

## Task 4: Router

**Files:**
- Create: `src/familylink_server/routers/linux_machines.py`
- Create: `tests/server/test_routers_linux_machines.py`

**Interfaces:**
- Consumes:
  - `LinuxMachine`, `LinuxUsageSnapshot` (Task 1)
  - `lock_session`, `poweroff_machine` (Task 2)
  - `get_session` (FastAPI dependency, already in db/__init__.py)
  - `get_service` (FamilyLinkService, already exists)
- Produces: `router` (FastAPI `APIRouter`) imported by `main.py` in Task 6.

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_routers_linux_machines.py`:

```python
"""Tests for /linux-machines router."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer

from familylink_server.config import settings
from familylink_server.db import get_session


def _cookie() -> str:
    s = URLSafeSerializer(settings.secret_key, salt='fl-session')
    return s.dumps({'email': settings.familylink_google_email})


def _mock_svc(children: list | None = None) -> MagicMock:
    children = children or []
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(members=children)
    )
    return mock_svc


def _mock_session(machines: list | None = None, machine: MagicMock | None = None) -> MagicMock:
    """Build a mock AsyncSession that returns machines from execute() and machine from get()."""
    machines = machines or []
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = machines
    mock_exec_result.scalar_one_or_none.return_value = None

    mock_s = AsyncMock()
    mock_s.execute = AsyncMock(return_value=mock_exec_result)
    mock_s.get = AsyncMock(return_value=machine)
    mock_s.add = MagicMock()
    mock_s.flush = AsyncMock()
    mock_s.commit = AsyncMock()
    mock_s.delete = AsyncMock()
    return mock_s


def test_linux_machines_page_returns_200():
    """GET /linux-machines with auth returns 200."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session()
    try:
        client = TestClient(app)
        resp = client.get('/linux-machines', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200


def test_linux_machines_page_requires_auth():
    """GET /linux-machines without auth redirects."""
    from familylink_server.main import app

    client = TestClient(app, follow_redirects=False)
    resp = client.get('/linux-machines')
    assert resp.status_code in (302, 307)


def test_create_machine_redirects():
    """POST /linux-machines creates machine and redirects to list."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session()
    try:
        client = TestClient(app, follow_redirects=False)
        resp = client.post(
            '/linux-machines',
            data={
                'friendly_name': 'Test PC',
                'child_id': 'child1',
                'hostname': '192.168.1.10',
                'ssh_port': '22',
                'ssh_user': 'kid',
                'ssh_private_key': '-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----',
                'grace_period_mins': '5',
            },
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 303
    assert resp.headers['location'] == '/linux-machines'


def test_lock_machine_returns_partial_html():
    """POST /linux-machines/{id}/lock returns HTML partial with 'locked'."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service
    from unittest.mock import patch

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.hostname = 'host'
    mock_machine.ssh_port = 22
    mock_machine.ssh_user = 'user'
    mock_machine.ssh_private_key = 'key'
    mock_machine.friendly_name = 'Test PC'
    mock_machine.child_id = 'child1'
    mock_machine.daily_limit_mins = 60
    mock_machine.grace_period_mins = 5

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session(machine=mock_machine)
    try:
        client = TestClient(app)
        with patch(
            'familylink_server.routers.linux_machines.lock_session', AsyncMock()
        ):
            resp = client.post(
                '/linux-machines/1/lock',
                cookies={'fl_session': _cookie()},
            )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'locked' in resp.text.lower()


def test_poweroff_machine_returns_partial_html():
    """POST /linux-machines/{id}/poweroff returns HTML partial with 'powered'."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service
    from unittest.mock import patch

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.hostname = 'host'
    mock_machine.ssh_port = 22
    mock_machine.ssh_user = 'user'
    mock_machine.ssh_private_key = 'key'
    mock_machine.friendly_name = 'Test PC'
    mock_machine.child_id = 'child1'
    mock_machine.daily_limit_mins = 60
    mock_machine.grace_period_mins = 5

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session(machine=mock_machine)
    try:
        client = TestClient(app)
        with patch(
            'familylink_server.routers.linux_machines.poweroff_machine', AsyncMock()
        ):
            resp = client.post(
                '/linux-machines/1/poweroff',
                cookies={'fl_session': _cookie()},
            )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'powered' in resp.text.lower()


def test_delete_machine_returns_empty():
    """DELETE /linux-machines/{id} returns empty 200 for HTMX removal."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session(machine=mock_machine)
    try:
        client = TestClient(app)
        resp = client.delete(
            '/linux-machines/1',
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert resp.text == ''
```

- [ ] **Step 2: Run tests — expect ImportError (router not wired yet)**

```bash
python -m pytest tests/server/test_routers_linux_machines.py -v
```

Expected: errors importing or 404s — the router isn't wired into `main.py` yet.

- [ ] **Step 3: Implement the router**

Create `src/familylink_server/routers/linux_machines.py`:

```python
"""Router for /linux-machines CRUD and HTMX action endpoints."""

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import get_session
from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot
from familylink_server.services.family_link import FamilyLinkService, get_service
from familylink_server.services.linux_ssh import lock_session, poweroff_machine

router = APIRouter(tags=['linux_machines'])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / 'templates'))


async def _get_machine_or_404(machine_id: int, session: AsyncSession) -> LinuxMachine:
    machine = await session.get(LinuxMachine, machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail='Machine not found')
    return machine


async def _today_snapshot(machine_id: int, session: AsyncSession) -> LinuxUsageSnapshot | None:
    result = await session.execute(
        select(LinuxUsageSnapshot).where(
            LinuxUsageSnapshot.machine_id == machine_id,
            LinuxUsageSnapshot.date == date.today(),
        )
    )
    return result.scalar_one_or_none()


def _machine_context(machine: LinuxMachine, snapshot: LinuxUsageSnapshot | None) -> dict:
    active_mins = (snapshot.active_seconds // 60) if snapshot else 0
    if snapshot and snapshot.poweroff_at:
        status = 'powered_off'
    elif snapshot and snapshot.locked_at:
        status = 'locked'
    else:
        status = 'active'
    return {'machine': machine, 'active_mins': active_mins, 'status': status}


async def _child_names(svc: FamilyLinkService) -> dict[str, str]:
    members = await svc.get_members()
    return {m.user_id: m.profile.display_name for m in members.members}


@router.get('/linux-machines', response_class=HTMLResponse)
async def linux_machines_page(
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Render the Linux Machines page."""
    result = await session.execute(select(LinuxMachine).order_by(LinuxMachine.friendly_name))
    machines = result.scalars().all()
    children = await _child_names(svc)
    rows = []
    for m in machines:
        snapshot = await _today_snapshot(m.id, session)
        ctx = _machine_context(m, snapshot)
        ctx['child_name'] = children.get(m.child_id, m.child_id)
        rows.append(ctx)
    return templates.TemplateResponse(
        request,
        'linux_machines.html',
        {'machines': rows, 'children': children},
    )


@router.get('/linux-machines/new', response_class=HTMLResponse)
async def new_machine_form(
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Render the add-machine form."""
    children = await _child_names(svc)
    return templates.TemplateResponse(
        request,
        'linux_machine_form.html',
        {'machine': None, 'children': children},
    )


@router.post('/linux-machines')
async def create_machine(
    friendly_name: str = Form(...),
    child_id: str = Form(...),
    hostname: str = Form(...),
    ssh_port: int = Form(22),
    ssh_user: str = Form(...),
    ssh_private_key: str = Form(...),
    daily_limit_mins: int | None = Form(None),
    grace_period_mins: int = Form(5),
    enabled: bool = Form(False),
    _email: str = require_user,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RedirectResponse:
    """Create a new Linux machine record."""
    session.add(LinuxMachine(
        friendly_name=friendly_name,
        child_id=child_id,
        hostname=hostname,
        ssh_port=ssh_port,
        ssh_user=ssh_user,
        ssh_private_key=ssh_private_key,
        daily_limit_mins=daily_limit_mins,
        grace_period_mins=grace_period_mins,
        enabled=enabled,
        created_at=datetime.now(UTC),
    ))
    await session.commit()
    return RedirectResponse('/linux-machines', status_code=303)


@router.get('/linux-machines/{machine_id}/edit', response_class=HTMLResponse)
async def edit_machine_form(
    machine_id: int,
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Render the edit-machine form."""
    machine = await _get_machine_or_404(machine_id, session)
    children = await _child_names(svc)
    return templates.TemplateResponse(
        request,
        'linux_machine_form.html',
        {'machine': machine, 'children': children},
    )


@router.post('/linux-machines/{machine_id}/edit')
async def update_machine(
    machine_id: int,
    friendly_name: str = Form(...),
    child_id: str = Form(...),
    hostname: str = Form(...),
    ssh_port: int = Form(22),
    ssh_user: str = Form(...),
    ssh_private_key: str = Form(''),
    daily_limit_mins: int | None = Form(None),
    grace_period_mins: int = Form(5),
    enabled: bool = Form(False),
    _email: str = require_user,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RedirectResponse:
    """Update an existing Linux machine record."""
    machine = await _get_machine_or_404(machine_id, session)
    machine.friendly_name = friendly_name
    machine.child_id = child_id
    machine.hostname = hostname
    machine.ssh_port = ssh_port
    machine.ssh_user = ssh_user
    if ssh_private_key.strip():
        machine.ssh_private_key = ssh_private_key
    machine.daily_limit_mins = daily_limit_mins
    machine.grace_period_mins = grace_period_mins
    machine.enabled = enabled
    await session.commit()
    return RedirectResponse('/linux-machines', status_code=303)


@router.delete('/linux-machines/{machine_id}', response_class=HTMLResponse)
async def delete_machine(
    machine_id: int,
    _email: str = require_user,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Delete a Linux machine and return empty string for HTMX outerHTML swap."""
    machine = await _get_machine_or_404(machine_id, session)
    await session.delete(machine)
    await session.commit()
    return HTMLResponse('')


@router.post('/linux-machines/{machine_id}/lock', response_class=HTMLResponse)
async def lock_machine(
    machine_id: int,
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Lock the machine immediately and return the updated card partial."""
    machine = await _get_machine_or_404(machine_id, session)
    await lock_session(machine.hostname, machine.ssh_port, machine.ssh_user, machine.ssh_private_key)
    snapshot = await _today_snapshot(machine_id, session)
    now = datetime.now(UTC)
    if snapshot is None:
        snapshot = LinuxUsageSnapshot(
            machine_id=machine_id,
            date=date.today(),
            active_seconds=0,
            updated_at=now,
        )
        session.add(snapshot)
    if snapshot.locked_at is None:
        snapshot.locked_at = now
        snapshot.updated_at = now
    await session.commit()
    children = await _child_names(svc)
    ctx = _machine_context(machine, snapshot)
    ctx['child_name'] = children.get(machine.child_id, machine.child_id)
    return templates.TemplateResponse(request, 'partials/linux_machine_card.html', ctx)


@router.post('/linux-machines/{machine_id}/poweroff', response_class=HTMLResponse)
async def poweroff_machine_endpoint(
    machine_id: int,
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Power off the machine immediately and return the updated card partial."""
    machine = await _get_machine_or_404(machine_id, session)
    await poweroff_machine(machine.hostname, machine.ssh_port, machine.ssh_user, machine.ssh_private_key)
    snapshot = await _today_snapshot(machine_id, session)
    now = datetime.now(UTC)
    if snapshot is None:
        snapshot = LinuxUsageSnapshot(
            machine_id=machine_id,
            date=date.today(),
            active_seconds=0,
            updated_at=now,
        )
        session.add(snapshot)
    if snapshot.locked_at is None:
        snapshot.locked_at = now
    snapshot.poweroff_at = now
    snapshot.updated_at = now
    await session.commit()
    children = await _child_names(svc)
    ctx = _machine_context(machine, snapshot)
    ctx['child_name'] = children.get(machine.child_id, machine.child_id)
    return templates.TemplateResponse(request, 'partials/linux_machine_card.html', ctx)
```

- [ ] **Step 4: Run tests — still failing (router not wired, templates missing)**

```bash
python -m pytest tests/server/test_routers_linux_machines.py -v
```

Expected: errors about missing templates or 404 (router not in app yet). That's OK — templates and wiring come next. Keep going.

- [ ] **Step 5: Commit router**

```bash
git add src/familylink_server/routers/linux_machines.py tests/server/test_routers_linux_machines.py
git commit -m "feat: add Linux machines router with CRUD and lock/poweroff endpoints"
```

---

## Task 5: Templates and navigation

**Files:**
- Create: `src/familylink_server/templates/linux_machines.html`
- Create: `src/familylink_server/templates/linux_machine_form.html`
- Create: `src/familylink_server/templates/partials/linux_machine_card.html`
- Modify: `src/familylink_server/templates/base.html`

**Interfaces:**
- Consumes context keys from router: `machine`, `machines`, `active_mins`, `status`, `child_name`, `children`.
- No new tests — template correctness is verified by the router tests in Task 4.

- [ ] **Step 1: Create the card partial**

Create `src/familylink_server/templates/partials/linux_machine_card.html`:

```html
<div id="linux-machine-{{ machine.id }}" class="card">
  <header>
    <strong>{{ machine.friendly_name }}</strong>
    {% if status == 'powered_off' %}
      <span class="badge" style="color:var(--pico-color-red-700)">powered off</span>
    {% elif status == 'locked' %}
      <span class="badge" style="color:var(--pico-color-orange-500)">locked</span>
    {% else %}
      <span class="badge" style="color:var(--pico-color-green-500)">active</span>
    {% endif %}
  </header>
  <p>
    <small>{{ machine.hostname }} &mdash; {{ child_name }}</small><br>
    {% if machine.daily_limit_mins %}
      <small>{{ active_mins }} / {{ machine.daily_limit_mins }} min used today</small>
      <progress value="{{ active_mins }}" max="{{ machine.daily_limit_mins }}"></progress>
    {% else %}
      <small>No daily limit</small>
    {% endif %}
  </p>
  <footer>
    {% if status != 'powered_off' %}
      <form hx-post="/linux-machines/{{ machine.id }}/lock"
            hx-target="#linux-machine-{{ machine.id }}"
            hx-swap="outerHTML"
            style="display:inline">
        <button type="submit" class="secondary">Lock now</button>
      </form>
      <form hx-post="/linux-machines/{{ machine.id }}/poweroff"
            hx-target="#linux-machine-{{ machine.id }}"
            hx-swap="outerHTML"
            style="display:inline">
        <button type="submit" class="contrast">Power off</button>
      </form>
    {% endif %}
    <a href="/linux-machines/{{ machine.id }}/edit" role="button" class="outline">Edit</a>
    <button hx-delete="/linux-machines/{{ machine.id }}"
            hx-target="#linux-machine-{{ machine.id }}"
            hx-swap="outerHTML"
            hx-confirm="Delete {{ machine.friendly_name }}?"
            class="outline secondary">Delete</button>
  </footer>
</div>
```

- [ ] **Step 2: Create the list page**

Create `src/familylink_server/templates/linux_machines.html`:

```html
{% extends "base.html" %}
{% block title %}Linux Machines{% endblock %}
{% block content %}
<h2>Linux Machines</h2>
<p><a href="/linux-machines/new" role="button">Add machine</a></p>
<div class="grid">
  {% for row in machines %}
    {% set machine = row.machine %}
    {% set active_mins = row.active_mins %}
    {% set status = row.status %}
    {% set child_name = row.child_name %}
    {% include "partials/linux_machine_card.html" %}
  {% else %}
    <p>No Linux machines registered yet.</p>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 3: Create the add/edit form**

Create `src/familylink_server/templates/linux_machine_form.html`:

```html
{% extends "base.html" %}
{% block title %}{% if machine %}Edit{% else %}Add{% endif %} Linux Machine{% endblock %}
{% block content %}
<h2>{% if machine %}Edit{% else %}Add{% endif %} Linux Machine</h2>
<form method="post"
      action="{% if machine %}/linux-machines/{{ machine.id }}/edit{% else %}/linux-machines{% endif %}">
  <label>
    Friendly name
    <input name="friendly_name" value="{{ machine.friendly_name if machine else '' }}" required>
  </label>
  <label>
    Child
    <select name="child_id">
      {% for user_id, display_name in children.items() %}
        <option value="{{ user_id }}"
          {% if machine and machine.child_id == user_id %}selected{% endif %}>
          {{ display_name }}
        </option>
      {% endfor %}
    </select>
  </label>
  <div class="grid">
    <label>
      Hostname / IP
      <input name="hostname" value="{{ machine.hostname if machine else '' }}" required>
    </label>
    <label>
      SSH port
      <input name="ssh_port" type="number" value="{{ machine.ssh_port if machine else 22 }}" required>
    </label>
  </div>
  <label>
    SSH user
    <input name="ssh_user" value="{{ machine.ssh_user if machine else '' }}" required>
  </label>
  <label>
    SSH private key (PEM){% if machine %} — leave blank to keep existing{% endif %}
    <textarea name="ssh_private_key" rows="8"
      placeholder="-----BEGIN RSA PRIVATE KEY-----&#10;...">{% if not machine %}{% endif %}</textarea>
  </label>
  <div class="grid">
    <label>
      Daily limit (minutes, leave blank for no limit)
      <input name="daily_limit_mins" type="number" min="1"
             value="{{ machine.daily_limit_mins if machine and machine.daily_limit_mins else '' }}">
    </label>
    <label>
      Grace period before poweroff (minutes)
      <input name="grace_period_mins" type="number" min="1"
             value="{{ machine.grace_period_mins if machine else 5 }}" required>
    </label>
  </div>
  <label>
    <input name="enabled" type="checkbox" role="switch"
           {% if not machine or machine.enabled %}checked{% endif %}>
    Enabled
  </label>
  <button type="submit">{% if machine %}Save{% else %}Add machine{% endif %}</button>
  <a href="/linux-machines">Cancel</a>
</form>
{% endblock %}
```

- [ ] **Step 4: Add Linux Machines to nav in base.html**

In `src/familylink_server/templates/base.html`, add the nav link after `<li><a href="/devices">Devices</a></li>`:

```html
        <li><a href="/linux-machines">Linux Machines</a></li>
```

The full `<ul>` block becomes:

```html
      <ul>
        <li><a href="/">Dashboard</a></li>
        <li><a href="/apps">Apps</a></li>
        <li><a href="/devices">Devices</a></li>
        <li><a href="/linux-machines">Linux Machines</a></li>
        <li><a href="/history">History</a></li>
        <li><a href="/auth/logout" class="secondary">Logout</a></li>
      </ul>
```

- [ ] **Step 5: Commit templates**

```bash
git add \
  src/familylink_server/templates/linux_machines.html \
  src/familylink_server/templates/linux_machine_form.html \
  src/familylink_server/templates/partials/linux_machine_card.html \
  src/familylink_server/templates/base.html
git commit -m "feat: add Linux machines templates and nav link"
```

---

## Task 6: Wire router and poller into main.py

**Files:**
- Modify: `src/familylink_server/main.py`

**Interfaces:**
- Consumes:
  - `router` from `familylink_server.routers.linux_machines` (Task 4)
  - `poller_loop` from `familylink_server.services.linux_poller` (Task 3)
- Produces: running application with `/linux-machines` routes and background poller.

- [ ] **Step 1: Write a wiring smoke test**

Add to `tests/server/test_main.py` (existing file — append the test):

```python
def test_linux_machines_route_is_registered():
    """GET /linux-machines is registered in the app."""
    from familylink_server.main import app
    routes = [r.path for r in app.routes]
    assert '/linux-machines' in routes
```

- [ ] **Step 2: Run smoke test — expect failure**

```bash
python -m pytest tests/server/test_main.py::test_linux_machines_route_is_registered -v
```

Expected: FAIL — route not registered yet.

- [ ] **Step 3: Wire into main.py**

In `src/familylink_server/main.py`, add the imports alongside the existing router imports:

```python
from familylink_server.routers.linux_machines import router as linux_machines_router
from familylink_server.services.linux_poller import poller_loop
```

Inside the `lifespan` function, after the Discord bot block and before `yield`, add the poller task:

```python
    poller_task = asyncio.create_task(poller_loop())
    logger.info('Linux machine poller started')

    yield

    poller_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller_task
```

The existing `yield` and Discord bot cancellation must be merged so that both the Discord bot task and the poller task are cancelled on shutdown. The full lifespan body becomes:

```python
@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize services at startup; shut down cleanly."""
    init_service()

    bot_task: asyncio.Task | None = None
    if settings.discord_enabled:
        from familylink_server.bot.client import FamilyLinkBot, _bot_task_with_restart
        from familylink_server.services.discord_notifier import init_notifier

        notifier = init_notifier(settings.discord_channel_id)  # type: ignore[arg-type]
        bot = FamilyLinkBot(
            service=get_service(),
            notifier=notifier,
            guild_id=settings.discord_guild_id,  # type: ignore[arg-type]
            summary_time=settings.discord_summary_time_parsed,
        )
        bot_task = asyncio.create_task(
            _bot_task_with_restart(bot, settings.discord_bot_token)  # type: ignore[arg-type]
        )
        logger.info('Discord bot task started')
    else:
        logger.info(
            'Discord bot disabled (DISCORD_BOT_TOKEN / GUILD_ID / CHANNEL_ID not set)'
        )

    poller_task = asyncio.create_task(poller_loop())
    logger.info('Linux machine poller started')

    yield

    poller_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller_task

    if bot_task is not None:
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task
```

After the `app.include_router(devices_router)` line, add:

```python
app.include_router(linux_machines_router)
```

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/server/ -v
```

Expected: all tests PASS. Pay attention to any test that patches `lifespan` — if the poller task causes issues in tests that mock the DB, those tests will need `TestClient(app)` which skips lifespan by default when using `with TestClient(app):` context, so they should be fine.

- [ ] **Step 5: Run ruff**

```bash
ruff check src tests && ruff format src tests
```

Expected: no errors. Fix any that appear.

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/main.py tests/server/test_main.py
git commit -m "feat: wire Linux machines router and poller into app lifespan"
```

---

## Self-Review

**Spec coverage:**
- [x] SSH-based control (no agent on Linux box) — `linux_ssh.py`
- [x] Machine registration via web UI stored in DB — `linux_machines.py` router + `LinuxMachine` model
- [x] Server-side SSH polling every 60 s — `linux_poller.py` `POLL_INTERVAL = 60`
- [x] Soft lock on session exhaustion — `loginctl lock-sessions` in `poll_machine`
- [x] Hard poweroff after grace period — `systemctl poweroff` in `poll_machine`
- [x] `daily_limit_mins` and `grace_period_mins` configurable in UI — form fields + model columns
- [x] Manual lock/poweroff from UI — `/lock` and `/poweroff` endpoints
- [x] `asyncssh>=2.14` dependency — added to `pyproject.toml`
- [x] Alembic migration — `002_linux_machines.py`
- [x] Linux Machines nav link — `base.html`

**Placeholder scan:** No TBDs or incomplete steps.

**Type consistency:**
- `check_session`, `lock_session`, `poweroff_machine` signatures match between `linux_ssh.py` (definition) and `linux_poller.py` + `routers/linux_machines.py` (callers).
- `poll_machine(machine: LinuxMachine)` defined and called consistently.
- `poller_loop()` defined and called in `main.py`.
- `make_session()` exported from `db/__init__.py` and `db/session.py`, imported in `linux_poller.py`.
