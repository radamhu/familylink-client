# Linux Bonus Time Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-day bonus screen time to Linux machines: a `bonus_mins` DB column, an HTTP `/bonus` endpoint, Discord `/linux bonus` command, poller notifications on lock/poweroff, Linux usage on the web dashboard, and Linux data in Discord `/status` and daily summaries.

**Architecture:** `bonus_mins` lives on `linux_usage_snapshots` (today-only, resets daily). The effective lock threshold becomes `(daily_limit_mins + bonus_mins) * 60`. A new `unlock_session` SSH helper reverses a soft lock. The Discord bot receives `make_session` so it can read/write Linux data; the poller receives an optional `DiscordNotifier` for event notifications.

**Tech Stack:** SQLAlchemy async ORM, Alembic, FastAPI + Jinja2 + HTMX, asyncssh, discord.py, pytest + pytest-mock.

## Global Constraints

- Python 3.12 (pyenv `.python-version`). Run `python -m pytest`, never `uv run pytest`.
- Single-quoted inline strings, Google docstring style — enforced by ruff.
- `asyncio_mode = "auto"` in pytest — all `async def test_*` run automatically.
- All server tests set env vars in `tests/server/conftest.py` before importing app modules.
- Install: `pip install -e ".[dev,test,server]"`.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `alembic/versions/003_bonus_mins.py` | Migration: add `bonus_mins` to `linux_usage_snapshots` |
| Modify | `src/familylink_server/db/models.py` | Add `bonus_mins` field to `LinuxUsageSnapshot` |
| Modify | `src/familylink_server/services/linux_ssh.py` | Add `unlock_session()` helper |
| Modify | `src/familylink_server/services/linux_poller.py` | Effective limit; optional notifier; fire on lock/poweroff |
| Modify | `src/familylink_server/routers/linux_machines.py` | `/bonus` endpoint; update `_machine_context()` |
| Modify | `src/familylink_server/routers/dashboard.py` | Add `session` dep; query Linux machines per child |
| Modify | `src/familylink_server/templates/partials/linux_machine_card.html` | Bonus buttons; progress bar uses `effective_limit_mins` |
| Modify | `src/familylink_server/templates/linux_machines.html` | Unpack `effective_limit_mins`/`bonus_mins` from row |
| Modify | `src/familylink_server/templates/dashboard.html` | Linux Machines subsection per child |
| Modify | `src/familylink_server/bot/embeds.py` | `_ACTION_MAP` entries; `linux_machines` param on status/summary |
| Modify | `src/familylink_server/services/discord_notifier.py` | `linux_machines` param on `post_daily_summary` / `_summary_embed` |
| Create | `src/familylink_server/bot/commands/linux.py` | `LinuxGroup` with `/linux bonus` command |
| Modify | `src/familylink_server/bot/client.py` | Accept `make_session`; register `LinuxGroup`; Linux data in status+summary |
| Modify | `src/familylink_server/main.py` | Hoist notifier; pass to poller + bot |
| Modify | `tests/server/test_linux_ssh.py` | Add `unlock_session` test |
| Modify | `tests/server/test_linux_poller.py` | Update `_make_snapshot`; add bonus threshold + notifier tests |
| Modify | `tests/server/test_routers_linux_machines.py` | Add bonus endpoint tests |
| Modify | `tests/server/test_routers_dashboard.py` | Override `get_session`; add Linux machines test |
| Modify | `tests/server/test_bot_embeds.py` | Add Linux-extended embed tests |
| Create | `tests/server/test_bot_linux.py` | `LinuxGroup` bonus command tests |

---

## Task 1: DB migration + model

**Files:**
- Modify: `src/familylink_server/db/models.py`
- Create: `alembic/versions/003_bonus_mins.py`
- Modify: `tests/server/test_linux_poller.py` (update `_make_snapshot` fixture)
- Modify: `tests/server/test_db_models.py`

**Interfaces:**
- Produces: `LinuxUsageSnapshot.bonus_mins: Mapped[int]` (default 0) — used by Tasks 3, 4, 5, 7, 8.

- [ ] **Step 1: Write failing model test**

Add to `tests/server/test_db_models.py`:

```python
def test_linux_usage_snapshot_has_bonus_mins_defaulting_to_zero():
    """LinuxUsageSnapshot.bonus_mins defaults to 0."""
    import datetime
    from familylink_server.db.models import LinuxUsageSnapshot

    snap = LinuxUsageSnapshot(
        machine_id=1,
        date=datetime.date.today(),
        active_seconds=0,
        updated_at=datetime.datetime.now(datetime.UTC),
    )
    assert snap.bonus_mins == 0


def test_linux_usage_snapshot_bonus_mins_stores_value():
    """LinuxUsageSnapshot.bonus_mins stores an explicit value."""
    import datetime
    from familylink_server.db.models import LinuxUsageSnapshot

    snap = LinuxUsageSnapshot(
        machine_id=1,
        date=datetime.date.today(),
        active_seconds=0,
        bonus_mins=30,
        updated_at=datetime.datetime.now(datetime.UTC),
    )
    assert snap.bonus_mins == 30
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/server/test_db_models.py::test_linux_usage_snapshot_has_bonus_mins_defaulting_to_zero tests/server/test_db_models.py::test_linux_usage_snapshot_bonus_mins_stores_value -v
```

Expected: FAIL — `LinuxUsageSnapshot.__init__` has no `bonus_mins`.

- [ ] **Step 3: Add `bonus_mins` to `LinuxUsageSnapshot` in `db/models.py`**

In `src/familylink_server/db/models.py`, update `LinuxUsageSnapshot`:

```python
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
    bonus_mins: Mapped[int] = mapped_column(Integer, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    poweroff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __init__(self, **kwargs: object) -> None:
        """Initialise with Python-level defaults for optional columns."""
        kwargs.setdefault('active_seconds', 0)
        kwargs.setdefault('bonus_mins', 0)
        kwargs.setdefault('locked_at', None)
        kwargs.setdefault('poweroff_at', None)
        super().__init__(**kwargs)
```

- [ ] **Step 4: Run model tests — expect PASS**

```bash
python -m pytest tests/server/test_db_models.py::test_linux_usage_snapshot_has_bonus_mins_defaulting_to_zero tests/server/test_db_models.py::test_linux_usage_snapshot_bonus_mins_stores_value -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Update `_make_snapshot` in `tests/server/test_linux_poller.py`**

Find the `_make_snapshot` function and add `bonus_mins`:

```python
def _make_snapshot(
    active_seconds: int = 0,
    locked_at: datetime.datetime | None = None,
    poweroff_at: datetime.datetime | None = None,
    bonus_mins: int = 0,
) -> MagicMock:
    snap = MagicMock()
    snap.active_seconds = active_seconds
    snap.locked_at = locked_at
    snap.poweroff_at = poweroff_at
    snap.bonus_mins = bonus_mins
    snap.updated_at = None
    return snap
```

- [ ] **Step 6: Create Alembic migration**

Create `alembic/versions/003_bonus_mins.py`:

```python
"""add bonus_mins to linux_usage_snapshots

Revision ID: 003
Revises: 002
Create Date: 2026-06-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '003'
down_revision: str | Sequence[str] | None = '002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add bonus_mins column to linux_usage_snapshots."""
    op.add_column(
        'linux_usage_snapshots',
        sa.Column('bonus_mins', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    """Drop bonus_mins column from linux_usage_snapshots."""
    op.drop_column('linux_usage_snapshots', 'bonus_mins')
```

- [ ] **Step 7: Run full poller test suite to confirm no regressions**

```bash
python -m pytest tests/server/test_linux_poller.py -v
```

Expected: all existing tests PASS (the `_make_snapshot` change is backward compatible).

- [ ] **Step 8: Commit**

```bash
git add src/familylink_server/db/models.py \
        alembic/versions/003_bonus_mins.py \
        tests/server/test_db_models.py \
        tests/server/test_linux_poller.py
git commit -m 'feat: add bonus_mins column to linux_usage_snapshots'
```

---

## Task 2: `unlock_session` SSH helper

**Files:**
- Modify: `src/familylink_server/services/linux_ssh.py`
- Modify: `tests/server/test_linux_ssh.py`

**Interfaces:**
- Produces: `unlock_session(hostname: str, port: int, user: str, key_text: str) -> None` — used by Tasks 4 and 7.

- [ ] **Step 1: Write failing test**

Add to `tests/server/test_linux_ssh.py`:

```python
async def test_unlock_session_runs_loginctl_unlock():
    """unlock_session issues loginctl unlock-sessions over SSH."""
    from familylink_server.services.linux_ssh import unlock_session

    mock_conn, mock_cm = _make_ssh_mock('')
    with (
        patch(
            'familylink_server.services.linux_ssh.asyncssh.import_private_key',
            return_value=MagicMock(),
        ),
        patch(
            'familylink_server.services.linux_ssh.asyncssh.connect',
            return_value=mock_cm,
        ),
    ):
        await unlock_session('host', 22, 'user', 'fake-pem')
    mock_conn.run.assert_awaited_once_with('loginctl unlock-sessions', check=False)
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
python -m pytest tests/server/test_linux_ssh.py::test_unlock_session_runs_loginctl_unlock -v
```

Expected: FAIL — `cannot import name 'unlock_session'`.

- [ ] **Step 3: Add `unlock_session` to `linux_ssh.py`**

Append to `src/familylink_server/services/linux_ssh.py`:

```python
async def unlock_session(hostname: str, port: int, user: str, key_text: str) -> None:
    """Unlock all sessions on the machine.

    Args:
        hostname: The SSH host to connect to.
        port: The SSH port number.
        user: The SSH username.
        key_text: PEM-encoded private key as a string.
    """
    key = asyncssh.import_private_key(key_text)
    async with asyncssh.connect(
        hostname,
        port=port,
        username=user,
        client_keys=[key],
        known_hosts=None,
        connect_timeout=10,
    ) as conn:
        await conn.run('loginctl unlock-sessions', check=False)
```

- [ ] **Step 4: Run test — expect PASS**

```bash
python -m pytest tests/server/test_linux_ssh.py -v
```

Expected: all 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/services/linux_ssh.py tests/server/test_linux_ssh.py
git commit -m 'feat: add unlock_session SSH helper'
```

---

## Task 3: Poller — effective limit + Discord notifications

**Files:**
- Modify: `src/familylink_server/services/linux_poller.py`
- Modify: `tests/server/test_linux_poller.py`

**Interfaces:**
- Consumes: `snapshot.bonus_mins: int` (Task 1), `DiscordNotifier.notify_change` (existing).
- Produces:
  - `poll_machine(machine: LinuxMachine, notifier: DiscordNotifier | None = None) -> None`
  - `poller_loop(notifier: DiscordNotifier | None = None) -> None`

- [ ] **Step 1: Write failing tests**

Add to `tests/server/test_linux_poller.py`:

```python
async def test_poll_machine_respects_bonus_mins_in_effective_limit():
    """Bonus mins extend the limit — machine is not locked when under effective threshold."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)  # 60 s limit
    # bonus_mins=1 → effective limit = 2 min = 120 s; active=60 s → below threshold
    snapshot = _make_snapshot(active_seconds=60, bonus_mins=1)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_lock = AsyncMock()
    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', mock_lock),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    mock_lock.assert_not_awaited()


async def test_poll_machine_notifies_on_soft_lock():
    """notify_change called with 'lock_linux' when soft lock is applied."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)
    snapshot = _make_snapshot(active_seconds=60, bonus_mins=0)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_notifier = AsyncMock()
    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', AsyncMock()),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, notifier=mock_notifier)

    mock_notifier.notify_change.assert_awaited_once_with(
        'lock_linux', machine.child_id, machine.friendly_name, 'poller'
    )


async def test_poll_machine_notifies_on_poweroff():
    """notify_change called with 'poweroff_linux' when poweroff is applied."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1, grace_period_mins=5)
    locked_ts = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=6)
    snapshot = _make_snapshot(active_seconds=120, locked_at=locked_ts, bonus_mins=0)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_notifier = AsyncMock()
    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=False),
        ),
        patch('familylink_server.services.linux_poller.poweroff_machine', AsyncMock()),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, notifier=mock_notifier)

    mock_notifier.notify_change.assert_awaited_once_with(
        'poweroff_linux', machine.child_id, machine.friendly_name, 'poller'
    )


async def test_poll_machine_no_crash_when_notifier_is_none():
    """poll_machine does not crash when notifier=None and lock is applied."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)
    snapshot = _make_snapshot(active_seconds=60, bonus_mins=0)
    mock_ctx, _ = _make_session_ctx(snapshot)

    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', AsyncMock()),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, notifier=None)  # must not raise
```

- [ ] **Step 2: Run new tests — expect FAIL**

```bash
python -m pytest tests/server/test_linux_poller.py::test_poll_machine_respects_bonus_mins_in_effective_limit tests/server/test_linux_poller.py::test_poll_machine_notifies_on_soft_lock tests/server/test_linux_poller.py::test_poll_machine_notifies_on_poweroff tests/server/test_linux_poller.py::test_poll_machine_no_crash_when_notifier_is_none -v
```

Expected: FAIL — signature mismatch or missing notifier logic.

- [ ] **Step 3: Update `linux_poller.py`**

Replace `src/familylink_server/services/linux_poller.py` with:

```python
"""Background asyncio task that polls Linux machines and enforces screen-time limits."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot
from familylink_server.db.session import make_session
from familylink_server.services.linux_ssh import (
    check_session,
    lock_session,
    poweroff_machine,
)

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60


async def poll_machine(
    machine: LinuxMachine, notifier: DiscordNotifier | None = None
) -> None:
    """Poll one machine: skip if powered off, accumulate active seconds, enforce limits.

    Args:
        machine: The LinuxMachine ORM instance to poll.
        notifier: Optional Discord notifier; posts on lock/poweroff when provided.
    """
    today = date.today()

    async with make_session() as session:
        stmt = select(LinuxUsageSnapshot).where(
            LinuxUsageSnapshot.machine_id == machine.id,
            LinuxUsageSnapshot.date == today,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.poweroff_at is not None:
            return

    try:
        active = await check_session(
            machine.hostname,
            machine.ssh_port,
            machine.ssh_user,
            machine.ssh_private_key,
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
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                snapshot = (await session.execute(stmt)).scalar_one()

        if active:
            snapshot.active_seconds += POLL_INTERVAL
            snapshot.updated_at = datetime.now(UTC)

        effective_limit_secs = (
            (machine.daily_limit_mins + snapshot.bonus_mins) * 60
            if machine.daily_limit_mins is not None
            else None
        )

        if (
            effective_limit_secs is not None
            and snapshot.active_seconds >= effective_limit_secs
            and snapshot.locked_at is None
        ):
            try:
                await lock_session(
                    machine.hostname,
                    machine.ssh_port,
                    machine.ssh_user,
                    machine.ssh_private_key,
                )
                snapshot.locked_at = datetime.now(UTC)
                logger.info('Soft lock applied to %s', machine.friendly_name)
                if notifier:
                    await notifier.notify_change(
                        'lock_linux', machine.child_id, machine.friendly_name, 'poller'
                    )
            except Exception:
                logger.warning('Lock failed for %s', machine.friendly_name)

        if snapshot.locked_at is not None and snapshot.poweroff_at is None:
            elapsed = (datetime.now(UTC) - snapshot.locked_at).total_seconds()
            if elapsed >= machine.grace_period_mins * 60:
                try:
                    await poweroff_machine(
                        machine.hostname,
                        machine.ssh_port,
                        machine.ssh_user,
                        machine.ssh_private_key,
                    )
                    snapshot.poweroff_at = datetime.now(UTC)
                    logger.info('Hard poweroff applied to %s', machine.friendly_name)
                    if notifier:
                        await notifier.notify_change(
                            'poweroff_linux',
                            machine.child_id,
                            machine.friendly_name,
                            'poller',
                        )
                except Exception:
                    snapshot.poweroff_at = datetime.now(UTC)
                    logger.warning(
                        'Poweroff failed for %s — marking as powered off to stop retries',
                        machine.friendly_name,
                    )

        await session.commit()


async def poller_loop(notifier: DiscordNotifier | None = None) -> None:
    """Main poll loop — iterates all enabled machines every POLL_INTERVAL seconds.

    Args:
        notifier: Optional Discord notifier passed down to each poll_machine call.
    """
    while True:
        try:
            async with make_session() as session:
                result = await session.execute(
                    select(LinuxMachine).where(LinuxMachine.enabled.is_(True))
                )
                machines = result.scalars().all()

            await asyncio.gather(
                *[poll_machine(m, notifier=notifier) for m in machines],
                return_exceptions=True,
            )
        except Exception:
            logger.exception('Poller cycle failed')
        await asyncio.sleep(POLL_INTERVAL)
```

- [ ] **Step 4: Run all poller tests — expect PASS**

```bash
python -m pytest tests/server/test_linux_poller.py -v
```

Expected: all 11 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/services/linux_poller.py tests/server/test_linux_poller.py
git commit -m 'feat: poller uses effective_limit and notifies Discord on lock/poweroff'
```

---

## Task 4: HTTP `/bonus` endpoint + card partial

**Files:**
- Modify: `src/familylink_server/routers/linux_machines.py`
- Modify: `src/familylink_server/templates/partials/linux_machine_card.html`
- Modify: `src/familylink_server/templates/linux_machines.html`
- Modify: `tests/server/test_routers_linux_machines.py`

**Interfaces:**
- Consumes: `unlock_session` (Task 2), `snapshot.bonus_mins` (Task 1).
- Produces:
  - `POST /linux-machines/{id}/bonus` → `partials/linux_machine_card.html`
  - `_machine_context()` gains keys `bonus_mins: int`, `effective_limit_mins: int | None`.

- [ ] **Step 1: Write failing tests**

Add to `tests/server/test_routers_linux_machines.py`:

```python
def test_bonus_adds_minutes_and_returns_card():
    """POST /linux-machines/{id}/bonus with minutes=15 returns 200 with card HTML."""
    from unittest.mock import patch
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.hostname = 'host'
    mock_machine.ssh_port = 22
    mock_machine.ssh_user = 'user'
    mock_machine.ssh_private_key = 'key'
    mock_machine.friendly_name = 'Gaming PC'
    mock_machine.child_id = 'child1'
    mock_machine.daily_limit_mins = 60
    mock_machine.grace_period_mins = 5

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session(machine=mock_machine)
    try:
        client = TestClient(app)
        with patch(
            'familylink_server.routers.linux_machines.unlock_session', AsyncMock()
        ):
            resp = client.post(
                '/linux-machines/1/bonus',
                data={'minutes': '15'},
                cookies={'fl_session': _cookie()},
            )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Gaming PC' in resp.text


def test_bonus_on_locked_machine_calls_unlock():
    """POST /bonus on locked machine calls unlock_session and resets locked_at."""
    from unittest.mock import patch
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.hostname = 'host'
    mock_machine.ssh_port = 22
    mock_machine.ssh_user = 'user'
    mock_machine.ssh_private_key = 'key'
    mock_machine.friendly_name = 'Gaming PC'
    mock_machine.child_id = 'child1'
    mock_machine.daily_limit_mins = 60
    mock_machine.grace_period_mins = 5

    import datetime
    locked_snap = MagicMock()
    locked_snap.active_seconds = 3600
    locked_snap.bonus_mins = 0
    locked_snap.locked_at = datetime.datetime.now(datetime.UTC)
    locked_snap.poweroff_at = None
    locked_snap.updated_at = None

    mock_s = AsyncMock()
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = []
    mock_exec_result.scalar_one_or_none.return_value = locked_snap
    mock_s.execute = AsyncMock(return_value=mock_exec_result)
    mock_s.get = AsyncMock(return_value=mock_machine)
    mock_s.add = MagicMock()
    mock_s.flush = AsyncMock()
    mock_s.commit = AsyncMock()

    mock_unlock = AsyncMock()
    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: mock_s
    try:
        client = TestClient(app)
        with patch(
            'familylink_server.routers.linux_machines.unlock_session', mock_unlock
        ):
            resp = client.post(
                '/linux-machines/1/bonus',
                data={'minutes': '30'},
                cookies={'fl_session': _cookie()},
            )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    mock_unlock.assert_awaited_once()
```

- [ ] **Step 2: Run new tests — expect FAIL (404 — endpoint doesn't exist)**

```bash
python -m pytest tests/server/test_routers_linux_machines.py::test_bonus_adds_minutes_and_returns_card tests/server/test_routers_linux_machines.py::test_bonus_on_locked_machine_calls_unlock -v
```

Expected: FAIL.

- [ ] **Step 3: Update `_machine_context` in `linux_machines.py`**

Replace the existing `_machine_context` function:

```python
def _machine_context(
    machine: LinuxMachine, snapshot: LinuxUsageSnapshot | None
) -> dict:
    active_mins = (snapshot.active_seconds // 60) if snapshot else 0
    bonus_mins = snapshot.bonus_mins if snapshot else 0
    if snapshot and snapshot.poweroff_at:
        status = 'powered_off'
    elif snapshot and snapshot.locked_at:
        status = 'locked'
    else:
        status = 'active'
    effective_limit_mins = (
        machine.daily_limit_mins + bonus_mins
        if machine.daily_limit_mins is not None
        else None
    )
    return {
        'machine': machine,
        'active_mins': active_mins,
        'bonus_mins': bonus_mins,
        'effective_limit_mins': effective_limit_mins,
        'status': status,
    }
```

- [ ] **Step 4: Add `unlock_session` import and `/bonus` endpoint to `linux_machines.py`**

Add `unlock_session` to the import line at the top of the file:

```python
from familylink_server.services.linux_ssh import lock_session, poweroff_machine, unlock_session
```

Append the following endpoint to `src/familylink_server/routers/linux_machines.py` (after the `poweroff_machine_endpoint`):

```python
@router.post('/linux-machines/{machine_id}/bonus', response_class=HTMLResponse)
async def bonus_machine(
    machine_id: int,
    request: Request,
    minutes: int = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Grant bonus minutes to a machine, unlocking it if currently locked."""
    machine = await _get_machine_or_404(machine_id, session)
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
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            snapshot = (
                await session.execute(
                    select(LinuxUsageSnapshot).where(
                        LinuxUsageSnapshot.machine_id == machine_id,
                        LinuxUsageSnapshot.date == date.today(),
                    )
                )
            ).scalar_one()
            now = datetime.now(UTC)
    snapshot.bonus_mins += minutes
    if snapshot.locked_at is not None and snapshot.poweroff_at is None:
        try:
            await unlock_session(
                machine.hostname,
                machine.ssh_port,
                machine.ssh_user,
                machine.ssh_private_key,
            )
            snapshot.locked_at = None
        except Exception:
            logger.warning('unlock_session failed for %s', machine.friendly_name)
    snapshot.updated_at = datetime.now(UTC)
    session.add(
        AuditLog(
            child_id=machine.child_id,
            action='bonus_linux',
            target=machine.friendly_name,
            new_value=str(minutes),
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    children = await _child_names(svc)
    ctx = _machine_context(machine, snapshot)
    ctx['child_name'] = children.get(machine.child_id, machine.child_id)
    return templates.TemplateResponse(request, 'partials/linux_machine_card.html', ctx)
```

- [ ] **Step 5: Update `linux_machines.html` to unpack new context keys**

In `src/familylink_server/templates/linux_machines.html`, update the for-loop to unpack the two new keys:

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
    {% set bonus_mins = row.bonus_mins %}
    {% set effective_limit_mins = row.effective_limit_mins %}
    {% set status = row.status %}
    {% set child_name = row.child_name %}
    {% include "partials/linux_machine_card.html" %}
  {% else %}
    <p>No Linux machines registered yet.</p>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 6: Update the card partial**

Replace `src/familylink_server/templates/partials/linux_machine_card.html`:

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
    {% if effective_limit_mins %}
      <small>{{ active_mins }} / {{ effective_limit_mins }} min used today{% if bonus_mins %} (+{{ bonus_mins }} bonus){% endif %}</small>
      <progress value="{{ active_mins }}" max="{{ effective_limit_mins }}"></progress>
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
      {% for mins in [15, 30, 60] %}
        <form hx-post="/linux-machines/{{ machine.id }}/bonus"
              hx-target="#linux-machine-{{ machine.id }}"
              hx-swap="outerHTML"
              style="display:inline">
          <input type="hidden" name="minutes" value="{{ mins }}">
          <button type="submit" class="outline">+{{ mins }} min</button>
        </form>
      {% endfor %}
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

- [ ] **Step 7: Run all linux_machines router tests — expect PASS**

```bash
python -m pytest tests/server/test_routers_linux_machines.py -v
```

Expected: all PASSED.

- [ ] **Step 8: Commit**

```bash
git add src/familylink_server/routers/linux_machines.py \
        src/familylink_server/templates/partials/linux_machine_card.html \
        src/familylink_server/templates/linux_machines.html \
        tests/server/test_routers_linux_machines.py
git commit -m 'feat: add /bonus HTTP endpoint with unlock and card partial bonus buttons'
```

---

## Task 5: Dashboard Linux section

**Files:**
- Modify: `src/familylink_server/routers/dashboard.py`
- Modify: `src/familylink_server/templates/dashboard.html`
- Modify: `tests/server/test_routers_dashboard.py`

**Interfaces:**
- Consumes: `LinuxMachine`, `LinuxUsageSnapshot`, `get_session` (all existing).
- Produces: `child["linux_machines"]: list[dict]` with keys `friendly_name`, `active_mins`, `effective_limit_mins`, `status`.

- [ ] **Step 1: Write failing tests**

In `tests/server/test_routers_dashboard.py`, replace the existing content with:

```python
"""Tests for the dashboard (/) and history (/history) routers."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer

from familylink_server.config import settings
from familylink_server.db import get_session


def _cookie():
    s = URLSafeSerializer(settings.secret_key, salt='fl-session')
    return s.dumps({'email': settings.familylink_google_email})


def _fake_session(machines=None):
    """Return an async generator yielding a mock session."""
    machines = machines or []

    async def _gen():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = machines
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session

    return _gen


def test_dashboard_returns_200():
    """GET / with a valid session and no children returns 200 with 'Family Link'."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))
    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Family Link' in resp.text


def test_dashboard_shows_linux_machine_for_child():
    """Dashboard renders Linux machine name when child has a registered machine."""
    import datetime
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.child_id = 'child1'
    mock_machine.friendly_name = 'Gaming PC'
    mock_machine.daily_limit_mins = 60
    mock_machine.enabled = True

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

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session(machines=[mock_machine])
    try:
        client = TestClient(app)
        resp = client.get('/', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Gaming PC' in resp.text


def test_history_returns_200():
    """GET /history with a valid session returns 200."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/history', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/server/test_routers_dashboard.py -v
```

Expected: `test_dashboard_returns_200` FAIL — `dashboard` handler has no `session` param yet.

- [ ] **Step 3: Update `dashboard.py`**

Replace `src/familylink_server/routers/dashboard.py`:

```python
"""Router for the main dashboard page."""

from datetime import UTC, date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import get_session
from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=['dashboard'])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / 'templates'))


@router.get('/', response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Render the dashboard with per-child usage summaries."""
    today = date.today()
    members = await svc.get_members()
    children = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    child_data = []
    for child in children:
        usage = await svc.get_apps_and_usage(child.user_id)
        today_sessions = [
            s
            for s in usage.app_usage_sessions
            if s.date.year == today.year
            and s.date.month == today.month
            and s.date.day == today.day
        ]
        total_seconds = sum(int(float(s.usage)) for s in today_sessions)
        top_apps: dict[str, int] = {}
        for s in today_sessions:
            pkg = s.app_id.android_app_package_name
            top_apps[pkg] = top_apps.get(pkg, 0) + int(float(s.usage))
        top5 = sorted(top_apps.items(), key=lambda x: x[1], reverse=True)[:5]
        title_by_pkg = {a.package_name: a.title for a in usage.apps}
        top5_named = [
            {'title': title_by_pkg.get(pkg, pkg), 'seconds': secs} for pkg, secs in top5
        ]
        devices = [
            {
                'device_id': d.device_id,
                'friendly_name': d.display_info.friendly_name,
                'is_locked': False,
            }
            for d in usage.device_info
        ]

        machine_result = await session.execute(
            select(LinuxMachine).where(
                LinuxMachine.child_id == child.user_id,
                LinuxMachine.enabled.is_(True),
            )
        )
        machines = machine_result.scalars().all()
        linux_rows = []
        for m in machines:
            snap_result = await session.execute(
                select(LinuxUsageSnapshot).where(
                    LinuxUsageSnapshot.machine_id == m.id,
                    LinuxUsageSnapshot.date == today,
                )
            )
            snap = snap_result.scalar_one_or_none()
            active_mins = (snap.active_seconds // 60) if snap else 0
            bonus_mins = snap.bonus_mins if snap else 0
            effective_limit_mins = (
                m.daily_limit_mins + bonus_mins if m.daily_limit_mins is not None else None
            )
            if snap and snap.poweroff_at:
                lm_status = 'powered_off'
            elif snap and snap.locked_at:
                lm_status = 'locked'
            else:
                lm_status = 'active'
            linux_rows.append({
                'friendly_name': m.friendly_name,
                'active_mins': active_mins,
                'effective_limit_mins': effective_limit_mins,
                'status': lm_status,
            })

        child_data.append({
            'display_name': child.profile.display_name,
            'user_id': child.user_id,
            'total_seconds': total_seconds,
            'top5': top5_named,
            'devices': devices,
            'linux_machines': linux_rows,
        })
    return templates.TemplateResponse(
        request,
        'dashboard.html',
        {'children': child_data},
    )
```

- [ ] **Step 4: Update `dashboard.html`**

Replace `src/familylink_server/templates/dashboard.html`:

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

      {% if child.linux_machines %}
        <h3>Linux Machines</h3>
        {% for lm in child.linux_machines %}
          <div style="margin-bottom:0.5rem">
            <span style="display:inline-block;width:12rem">{{ lm.friendly_name }}</span>
            {% if lm.effective_limit_mins %}
              <progress value="{{ lm.active_mins }}" max="{{ lm.effective_limit_mins }}"
                        style="display:inline-block;width:8rem;vertical-align:middle"></progress>
              <span style="font-size:0.8rem;color:var(--pico-muted-color)">
                {{ lm.active_mins }} / {{ lm.effective_limit_mins }} min
              </span>
            {% else %}
              <span style="font-size:0.8rem;color:var(--pico-muted-color)">no limit</span>
            {% endif %}
            {% if lm.status == 'powered_off' %}
              <span style="color:var(--pico-color-red-700);font-size:0.8rem">🔴 powered off</span>
            {% elif lm.status == 'locked' %}
              <span style="color:var(--pico-color-orange-500);font-size:0.8rem">🟠 locked</span>
            {% else %}
              <span style="color:var(--pico-color-green-500);font-size:0.8rem">🟢 active</span>
            {% endif %}
          </div>
        {% endfor %}
      {% endif %}
    </section>
  {% else %}
    <p>No supervised children found.</p>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: Run dashboard tests — expect PASS**

```bash
python -m pytest tests/server/test_routers_dashboard.py -v
```

Expected: all 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/routers/dashboard.py \
        src/familylink_server/templates/dashboard.html \
        tests/server/test_routers_dashboard.py
git commit -m 'feat: add Linux machines section to dashboard'
```

---

## Task 6: Discord embeds — extend for Linux data

**Files:**
- Modify: `src/familylink_server/bot/embeds.py`
- Modify: `src/familylink_server/services/discord_notifier.py`
- Modify: `tests/server/test_bot_embeds.py`

**Interfaces:**
- Produces:
  - `status_embed(children_data: list[dict]) -> discord.Embed` — each child dict gains optional `linux_machines` key.
  - `daily_summary_embed(child_name, top_apps, total_seconds, linux_machines=None) -> discord.Embed`
  - `post_daily_summary(..., linux_machines=None)` — passes through to `_summary_embed`.
  - `_ACTION_MAP` gains `lock_linux`, `poweroff_linux`, `bonus_linux`.

- [ ] **Step 1: Write failing tests**

Add to `tests/server/test_bot_embeds.py`:

```python
def test_action_map_has_linux_actions():
    """_ACTION_MAP contains lock_linux, poweroff_linux, bonus_linux."""
    from familylink_server.bot.embeds import _ACTION_MAP

    assert 'lock_linux' in _ACTION_MAP
    assert 'poweroff_linux' in _ACTION_MAP
    assert 'bonus_linux' in _ACTION_MAP


def test_status_embed_includes_linux_machines():
    """status_embed shows Linux machine info when linux_machines provided."""
    from familylink_server.bot.embeds import status_embed

    children_data = [
        {
            'name': 'Alice',
            'total_seconds': 3600,
            'device_count': 1,
            'linux_machines': [
                {
                    'friendly_name': 'Gaming PC',
                    'active_mins': 34,
                    'effective_limit_mins': 90,
                    'status': 'active',
                }
            ],
        }
    ]
    embed = status_embed(children_data)
    field_values = ' '.join(f.value for f in embed.fields)
    assert 'Gaming PC' in field_values


def test_daily_summary_embed_includes_linux_machines():
    """daily_summary_embed shows Linux section when linux_machines provided."""
    from familylink_server.bot.embeds import daily_summary_embed

    embed = daily_summary_embed(
        'Alice',
        [{'title': 'YouTube', 'seconds': 1800}],
        1800,
        linux_machines=[
            {
                'friendly_name': 'Homework PC',
                'active_mins': 20,
                'effective_limit_mins': 60,
                'status': 'active',
            }
        ],
    )
    field_names = ' '.join(f.name for f in embed.fields)
    field_values = ' '.join(f.value for f in embed.fields)
    assert 'Linux' in field_names or 'Homework PC' in field_values
```

- [ ] **Step 2: Run new tests — expect FAIL**

```bash
python -m pytest tests/server/test_bot_embeds.py::test_action_map_has_linux_actions tests/server/test_bot_embeds.py::test_status_embed_includes_linux_machines tests/server/test_bot_embeds.py::test_daily_summary_embed_includes_linux_machines -v
```

Expected: FAIL.

- [ ] **Step 3: Update `embeds.py`**

In `src/familylink_server/bot/embeds.py`, add entries to `_ACTION_MAP`:

```python
_ACTION_MAP: dict[str, tuple[str, discord.Color]] = {
    'block': ('🔒 App Blocked', discord.Color.red()),
    'always_allow': ('✅ App Always Allowed', discord.Color.green()),
    'set_limit': ('⏱️ App Limit Set', discord.Color.orange()),
    'lock_device': ('🔒 Device Locked', discord.Color.orange()),
    'unlock_device': ('🔓 Device Unlocked', discord.Color.green()),
    'lock_linux': ('🔒 Linux Machine Locked', discord.Color.orange()),
    'poweroff_linux': ('⚡ Linux Machine Powered Off', discord.Color.red()),
    'bonus_linux': ('⏰ Bonus Time Granted', discord.Color.green()),
}
```

Replace `status_embed`:

```python
def status_embed(children_data: list[dict]) -> discord.Embed:
    """Return a dashboard overview embed covering all children."""
    embed = discord.Embed(title='🏠 Family Status', color=discord.Color.blurple())
    for child in children_data:
        devices = f"{child['device_count']} device(s)"
        lines = [f"{_fmt(child['total_seconds'])} today · {devices}"]
        for lm in child.get('linux_machines', []):
            icon = {'powered_off': '🔴', 'locked': '🟠'}.get(lm['status'], '🟢')
            if lm['effective_limit_mins']:
                lines.append(
                    f"{icon} {lm['friendly_name']} {lm['active_mins']}/{lm['effective_limit_mins']}m"
                )
            else:
                lines.append(f"{icon} {lm['friendly_name']} (no limit)")
        embed.add_field(name=child['name'], value='\n'.join(lines), inline=False)
    return embed
```

Replace `daily_summary_embed`:

```python
def daily_summary_embed(
    child_name: str,
    top_apps: list[dict],
    total_seconds: int,
    linux_machines: list[dict] | None = None,
) -> discord.Embed:
    """Return a daily summary embed (used by the scheduled task)."""
    today = datetime.date.today().strftime('%A %d %b').lstrip(' ').replace(' ', ' ', 1)
    parts = today.split()
    day_str = str(int(parts[1])) if len(parts) > 1 else parts[0]
    today = f"{parts[0]} {day_str} {parts[2]}" if len(parts) > 2 else today
    embed = discord.Embed(
        title=f"📊 Daily Summary — {child_name}  ·  {today}",
        description=f"Total screen time: **{_fmt(total_seconds)}**",
        color=discord.Color.blurple(),
    )
    max_s = max((a['seconds'] for a in top_apps), default=1)
    for app in top_apps[:5]:
        embed.add_field(
            name=app['title'],
            value=f"`{_bar(app['seconds'], max_s)}` {_fmt(app['seconds'])}",
            inline=False,
        )
    if linux_machines:
        lines = []
        for lm in linux_machines:
            icon = {'powered_off': '🔴', 'locked': '🟠'}.get(lm['status'], '🟢')
            if lm['effective_limit_mins']:
                lines.append(
                    f"{icon} {lm['friendly_name']} {lm['active_mins']}/{lm['effective_limit_mins']}m"
                )
            else:
                lines.append(f"{icon} {lm['friendly_name']} (no limit)")
        embed.add_field(name='🖥️ Linux Machines', value='\n'.join(lines), inline=False)
    return embed
```

- [ ] **Step 4: Update `discord_notifier.py` — add `linux_machines` to `_summary_embed` and `post_daily_summary`**

In `src/familylink_server/services/discord_notifier.py`, replace `_summary_embed` and `post_daily_summary`:

```python
def _summary_embed(
    child_name: str,
    top_apps: list[dict],
    total_seconds: int,
    linux_machines: list[dict] | None = None,
) -> discord.Embed:
    """Build a daily summary embed."""
    import datetime

    today = datetime.date.today()
    today_str = f"{today.strftime('%A')} {today.day} {today.strftime('%b')}"
    h, rem = divmod(total_seconds, 3600)
    m = rem // 60
    total_str = f"{h}h {m:02d}m" if h else f"{m}m"
    embed = discord.Embed(
        title=f"📊 Daily Summary — {child_name}  ·  {today_str}",
        description=f"Total screen time: **{total_str}**",
        color=discord.Color.blurple(),
    )
    max_s = max((a['seconds'] for a in top_apps), default=1)
    for app in top_apps[:5]:
        ah, ar = divmod(app['seconds'], 3600)
        am = ar // 60
        dur = f"{ah}h {am:02d}m" if ah else f"{am}m"
        filled = round(app['seconds'] / max_s * 10)
        bar = '█' * filled + '░' * (10 - filled)
        embed.add_field(name=app['title'], value=f'`{bar}` {dur}', inline=False)
    if linux_machines:
        lines = []
        for lm in linux_machines:
            icon = {'powered_off': '🔴', 'locked': '🟠'}.get(lm['status'], '🟢')
            if lm['effective_limit_mins']:
                lines.append(
                    f"{icon} {lm['friendly_name']} {lm['active_mins']}/{lm['effective_limit_mins']}m"
                )
            else:
                lines.append(f"{icon} {lm['friendly_name']} (no limit)")
        embed.add_field(name='🖥️ Linux Machines', value='\n'.join(lines), inline=False)
    return embed


class DiscordNotifier:
    """Sends embeds to a configured Discord channel."""

    def __init__(self, channel_id: int) -> None:
        self._channel_id = channel_id
        self._channel: discord.TextChannel | None = None

    def set_channel(self, channel: discord.TextChannel) -> None:
        """Called by the bot's on_ready once the channel is resolved."""
        self._channel = channel
        logger.info('Discord notification channel set: #%s', channel.name)

    async def notify_change(
        self,
        action: str,
        child_name: str,
        target: str,
        source: str,
        view: discord.ui.View | None = None,
    ) -> None:
        """Post a change-alert embed. No-op if channel not yet ready."""
        if self._channel is None:
            return
        embed = _change_embed(action, child_name, target, source)
        await self._channel.send(embed=embed, view=view)

    async def post_daily_summary(
        self,
        child_name: str,
        top_apps: list[dict],
        total_seconds: int,
        linux_machines: list[dict] | None = None,
        view: discord.ui.View | None = None,
    ) -> None:
        """Post a daily usage summary embed. No-op if channel not yet ready."""
        if self._channel is None:
            return
        embed = _summary_embed(child_name, top_apps, total_seconds, linux_machines=linux_machines)
        await self._channel.send(embed=embed, view=view)
```

- [ ] **Step 5: Run embed tests — expect PASS**

```bash
python -m pytest tests/server/test_bot_embeds.py -v
```

Expected: all PASSED (including the 3 new tests).

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/bot/embeds.py \
        src/familylink_server/services/discord_notifier.py \
        tests/server/test_bot_embeds.py
git commit -m 'feat: extend Discord embeds with Linux machine data and actions'
```

---

## Task 7: `/linux bonus` Discord command

**Files:**
- Create: `src/familylink_server/bot/commands/linux.py`
- Create: `tests/server/test_bot_linux.py`

**Interfaces:**
- Consumes: `unlock_session` (Task 2), `LinuxMachine`, `LinuxUsageSnapshot`, `AuditLog` (Task 1), `make_session` (existing), `require_discord_role` (existing).
- Produces: `LinuxGroup(make_session)` — registered in Task 8.

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_bot_linux.py`:

```python
"""Tests for the /linux Discord command group."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


def _make_interaction(has_role: bool = True) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    member = MagicMock(spec=discord.Member)
    allowed_role = MagicMock()
    allowed_role.name = 'FamilyAdmin'
    member.roles = [allowed_role] if has_role else []
    interaction.user = member
    interaction.response = AsyncMock()
    return interaction


def _make_machine(machine_id: int = 1, friendly_name: str = 'Gaming PC') -> MagicMock:
    m = MagicMock()
    m.id = machine_id
    m.child_id = 'child1'
    m.friendly_name = friendly_name
    m.hostname = 'host'
    m.ssh_port = 22
    m.ssh_user = 'user'
    m.ssh_private_key = 'key'
    m.daily_limit_mins = 60
    m.enabled = True
    return m


def _make_session_ctx(machine=None, snapshot=None):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=machine)
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = snapshot
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


async def test_linux_bonus_grants_minutes():
    """'/linux bonus' adds bonus_mins to snapshot and replies with confirmation."""
    from familylink_server.bot.commands.linux import LinuxGroup

    machine = _make_machine()
    snap = MagicMock()
    snap.bonus_mins = 0
    snap.locked_at = None
    snap.poweroff_at = None
    snap.updated_at = None

    mock_ctx = _make_session_ctx(machine=machine, snapshot=snap)
    make_session = MagicMock(return_value=mock_ctx)

    group = LinuxGroup(make_session=make_session)
    interaction = _make_interaction()

    with patch('familylink_server.bot.commands.linux.require_discord_role', return_value=True):
        await group.bonus.callback(group, interaction, machine='1', minutes=15)

    assert snap.bonus_mins == 15
    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.call_args[0][0]
    assert '+15' in msg
    assert 'Gaming PC' in msg


async def test_linux_bonus_unlocks_when_locked():
    """'/linux bonus' calls unlock_session and mentions unlock in reply when machine was locked."""
    import datetime
    from familylink_server.bot.commands.linux import LinuxGroup

    machine = _make_machine()
    snap = MagicMock()
    snap.bonus_mins = 0
    snap.locked_at = datetime.datetime.now(datetime.UTC)
    snap.poweroff_at = None
    snap.updated_at = None

    mock_ctx = _make_session_ctx(machine=machine, snapshot=snap)
    make_session = MagicMock(return_value=mock_ctx)

    group = LinuxGroup(make_session=make_session)
    interaction = _make_interaction()

    mock_unlock = AsyncMock()
    with (
        patch('familylink_server.bot.commands.linux.require_discord_role', return_value=True),
        patch('familylink_server.bot.commands.linux.unlock_session', mock_unlock),
    ):
        await group.bonus.callback(group, interaction, machine='1', minutes=30)

    mock_unlock.assert_awaited_once()
    msg = interaction.response.send_message.call_args[0][0]
    assert 'unlocked' in msg.lower()


async def test_linux_bonus_requires_role():
    """'/linux bonus' replies with permission error without the Discord role."""
    from familylink_server.bot.commands.linux import LinuxGroup

    make_session = MagicMock()
    group = LinuxGroup(make_session=make_session)
    interaction = _make_interaction(has_role=False)

    with patch('familylink_server.bot.commands.linux.require_discord_role', return_value=False):
        await group.bonus.callback(group, interaction, machine='1', minutes=15)

    msg = interaction.response.send_message.call_args[1].get(
        'content'
    ) or interaction.response.send_message.call_args[0][0]
    assert 'permission' in msg.lower() or 'insufficient' in msg.lower()
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
python -m pytest tests/server/test_bot_linux.py -v
```

Expected: FAIL — `cannot import name 'LinuxGroup'`.

- [ ] **Step 3: Create `bot/commands/linux.py`**

Create `src/familylink_server/bot/commands/linux.py`:

```python
"""Discord /linux command group."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from familylink_server.bot.commands import require_discord_role
from familylink_server.db.models import AuditLog, LinuxMachine, LinuxUsageSnapshot
from familylink_server.services.linux_ssh import unlock_session

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession


class LinuxGroup(app_commands.Group, name='linux', description='Manage Linux machines'):
    """Slash command group: /linux bonus."""

    def __init__(
        self,
        make_session: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    ) -> None:
        super().__init__()
        self._make_session = make_session

    @app_commands.command(
        name='bonus', description='Grant extra screen time to a Linux machine'
    )
    @app_commands.describe(machine='Machine name', minutes='Extra minutes to grant')
    @app_commands.choices(
        minutes=[
            app_commands.Choice(name='+15 min', value=15),
            app_commands.Choice(name='+30 min', value=30),
            app_commands.Choice(name='+60 min', value=60),
        ]
    )
    async def bonus(
        self,
        interaction: discord.Interaction,
        machine: str,
        minutes: int,
    ) -> None:
        """Grant bonus minutes to a machine, unlocking if currently locked."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                'Insufficient permissions.', ephemeral=True
            )
            return
        try:
            machine_id = int(machine)
        except ValueError:
            await interaction.response.send_message(
                'Invalid machine selection.', ephemeral=True
            )
            return

        async with self._make_session() as session:
            db_machine = await session.get(LinuxMachine, machine_id)
            if db_machine is None:
                await interaction.response.send_message(
                    'Machine not found.', ephemeral=True
                )
                return

            today = date.today()
            stmt = select(LinuxUsageSnapshot).where(
                LinuxUsageSnapshot.machine_id == machine_id,
                LinuxUsageSnapshot.date == today,
            )
            snapshot = (await session.execute(stmt)).scalar_one_or_none()
            now = datetime.now(UTC)
            if snapshot is None:
                snapshot = LinuxUsageSnapshot(
                    machine_id=machine_id,
                    date=today,
                    active_seconds=0,
                    updated_at=now,
                )
                session.add(snapshot)
                try:
                    await session.flush()
                except IntegrityError:
                    await session.rollback()
                    snapshot = (await session.execute(stmt)).scalar_one()
                    now = datetime.now(UTC)

            snapshot.bonus_mins += minutes
            unlocked = False
            if snapshot.locked_at is not None and snapshot.poweroff_at is None:
                try:
                    await unlock_session(
                        db_machine.hostname,
                        db_machine.ssh_port,
                        db_machine.ssh_user,
                        db_machine.ssh_private_key,
                    )
                    snapshot.locked_at = None
                    unlocked = True
                except Exception:
                    pass

            snapshot.updated_at = datetime.now(UTC)
            session.add(
                AuditLog(
                    child_id=db_machine.child_id,
                    action='bonus_linux',
                    target=db_machine.friendly_name,
                    new_value=str(minutes),
                    occurred_at=datetime.now(UTC),
                )
            )
            await session.commit()

        msg = f"⏰ +{minutes} min granted for **{db_machine.friendly_name}**."
        if unlocked:
            msg += ' Machine unlocked.'
        await interaction.response.send_message(msg, ephemeral=True)

    @bonus.autocomplete('machine')
    async def machine_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete: return enabled machines whose name contains `current`."""
        async with self._make_session() as session:
            result = await session.execute(
                select(LinuxMachine).where(LinuxMachine.enabled.is_(True))
            )
            machines = result.scalars().all()
        return [
            app_commands.Choice(name=m.friendly_name, value=str(m.id))
            for m in machines
            if current.lower() in m.friendly_name.lower()
        ][:25]
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/server/test_bot_linux.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/bot/commands/linux.py tests/server/test_bot_linux.py
git commit -m 'feat: add /linux bonus Discord command'
```

---

## Task 8: Bot client + `main.py` wiring

**Files:**
- Modify: `src/familylink_server/bot/client.py`
- Modify: `src/familylink_server/main.py`
- Modify: `tests/server/test_main.py`

**Interfaces:**
- Consumes: `LinuxGroup` (Task 7), `daily_summary_embed` with `linux_machines` (Task 6), `status_embed` with `linux_machines` (Task 6), `poller_loop(notifier=...)` (Task 3).
- Produces: fully wired app — bot has DB access, poller fires Discord notifications.

- [ ] **Step 1: Write a wiring smoke test**

Add to `tests/server/test_main.py`:

```python
def test_poller_loop_accepts_notifier_kwarg():
    """poller_loop signature accepts a notifier keyword argument."""
    import inspect
    from familylink_server.services.linux_poller import poller_loop

    sig = inspect.signature(poller_loop)
    assert 'notifier' in sig.parameters
```

- [ ] **Step 2: Run test — expect PASS (already done in Task 3)**

```bash
python -m pytest tests/server/test_main.py::test_poller_loop_accepts_notifier_kwarg -v
```

Expected: PASS.

- [ ] **Step 3: Update `bot/client.py`**

Replace `src/familylink_server/bot/client.py`:

```python
"""Discord bot client and restart wrapper."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from familylink_server.bot.embeds import (
    daily_summary_embed,  # noqa: F401
    status_embed,
)
from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession

    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

logger = logging.getLogger(__name__)


def _linux_rows_for_child(
    machines: list,
    snapshots: dict,
) -> list[dict]:
    """Build linux_machines list for a child given ORM machine objects and snap map."""
    rows = []
    for m in machines:
        snap = snapshots.get(m.id)
        active_mins = (snap.active_seconds // 60) if snap else 0
        bonus_mins = snap.bonus_mins if snap else 0
        effective_limit_mins = (
            m.daily_limit_mins + bonus_mins if m.daily_limit_mins is not None else None
        )
        if snap and snap.poweroff_at:
            lm_status = 'powered_off'
        elif snap and snap.locked_at:
            lm_status = 'locked'
        else:
            lm_status = 'active'
        rows.append({
            'friendly_name': m.friendly_name,
            'active_mins': active_mins,
            'effective_limit_mins': effective_limit_mins,
            'status': lm_status,
        })
    return rows


async def _fetch_linux_rows(
    child_id: str,
    make_session: Callable[[], AbstractAsyncContextManager[AsyncSession]],
) -> list[dict]:
    """Query Linux machines + today's snapshots for one child."""
    today = date.today()
    async with make_session() as session:
        result = await session.execute(
            select(LinuxMachine).where(
                LinuxMachine.child_id == child_id,
                LinuxMachine.enabled.is_(True),
            )
        )
        machines = result.scalars().all()
        snap_map: dict[int, object] = {}
        for m in machines:
            snap_result = await session.execute(
                select(LinuxUsageSnapshot).where(
                    LinuxUsageSnapshot.machine_id == m.id,
                    LinuxUsageSnapshot.date == today,
                )
            )
            snap = snap_result.scalar_one_or_none()
            if snap:
                snap_map[m.id] = snap
    return _linux_rows_for_child(machines, snap_map)


class FamilyLinkBot(commands.Bot):
    """discord.py Bot subclass that wires in FamilyLinkService and DiscordNotifier."""

    def __init__(
        self,
        service: FamilyLinkService,
        notifier: DiscordNotifier,
        guild_id: int,
        summary_time: dt.time,
        make_session: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    ) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix='!', intents=intents)
        self.service = service
        self.notifier = notifier
        self.guild_id = guild_id
        self._summary_time = summary_time
        self._make_session = make_session
        self.daily_summary_task: tasks.Loop | None = None

    async def setup_hook(self) -> None:
        """Register command groups and create the scheduled task."""
        guild = discord.Object(id=self.guild_id)

        try:
            from familylink_server.bot.commands.apps import AppsGroup
            from familylink_server.bot.commands.devices import DevicesGroup
            from familylink_server.bot.commands.linux import LinuxGroup
            from familylink_server.bot.commands.usage import (
                UsageGroup,
                make_refresh_command,
                make_status_command,
            )

            self.tree.add_command(AppsGroup(self.service, self.notifier), guild=guild)
            self.tree.add_command(
                DevicesGroup(self.service, self.notifier), guild=guild
            )
            self.tree.add_command(UsageGroup(self.service, self.notifier), guild=guild)
            self.tree.add_command(LinuxGroup(make_session=self._make_session), guild=guild)
            self.tree.add_command(
                make_status_command(self.service, self._make_session), guild=guild
            )
            self.tree.add_command(make_refresh_command(self.service), guild=guild)
        except ImportError:
            logger.warning(
                'Bot command modules not yet available — skipping command registration'
            )

        self.daily_summary_task = tasks.loop(time=self._summary_time)(
            self._run_daily_summary
        )

        @self.tree.error
        async def on_tree_error(
            interaction: discord.Interaction,
            error: app_commands.AppCommandError,
        ) -> None:
            if isinstance(error, app_commands.CheckFailure):
                await interaction.response.send_message(
                    'You do not have permission to use this command.',
                    ephemeral=True,
                )
            else:
                logger.exception('Unhandled app command error', exc_info=error)

    async def on_ready(self) -> None:
        """Sync command tree, resolve channel, start summary task."""
        guild = discord.Object(id=self.guild_id)
        await self.tree.sync(guild=guild)
        logger.info(
            'Discord bot ready as %s — commands synced to guild %s',
            self.user,
            self.guild_id,
        )

        channel = self.get_channel(self.notifier._channel_id)
        if isinstance(channel, discord.TextChannel):
            self.notifier.set_channel(channel)
        else:
            logger.warning(
                'Discord channel %s not found or not a text channel',
                self.notifier._channel_id,
            )

        if (
            self.daily_summary_task is not None
            and not self.daily_summary_task.is_running()
        ):
            self.daily_summary_task.start()

    async def _run_daily_summary(self) -> None:
        """Post a daily usage summary embed for each supervised child."""
        try:
            from familylink_server.bot.views import SummaryView
        except ImportError:
            SummaryView = None  # type: ignore[assignment]

        try:
            members = await self.service.get_members()
            supervised = [
                m
                for m in members.members
                if m.member_supervision_info
                and m.member_supervision_info.is_supervised_member
            ]
            for child in supervised:
                usage = await self.service.get_apps_and_usage(child.user_id)
                all_apps_with_usage = sorted(
                    [
                        {'title': app.title, 'seconds': app.usage_today_seconds}
                        for app in usage.apps
                        if hasattr(app, 'usage_today_seconds') and app.usage_today_seconds
                    ],
                    key=lambda x: x['seconds'],
                    reverse=True,
                )
                total_seconds = sum(a['seconds'] for a in all_apps_with_usage)
                top_apps = all_apps_with_usage[:5]
                device_id = (
                    usage.device_info[0].device_id if usage.device_info else None
                )
                linux_rows = await _fetch_linux_rows(child.user_id, self._make_session)
                view = None
                if SummaryView is not None:
                    view = SummaryView(
                        self.service,
                        self.notifier,
                        child.user_id,
                        child.profile.display_name,
                        device_id,
                    )
                await self.notifier.post_daily_summary(
                    child.profile.display_name,
                    top_apps,
                    total_seconds,
                    linux_machines=linux_rows,
                    view=view,
                )
        except Exception:
            logger.exception('Error posting daily summary')


async def _bot_task_with_restart(bot: FamilyLinkBot, token: str) -> None:
    """Run bot.start() in a restart loop; exits cleanly on CancelledError."""
    while True:
        try:
            await bot.start(token)
        except asyncio.CancelledError:
            await bot.close()
            return
        except Exception:
            logger.exception('Discord bot crashed — restarting in 30 s')
            await asyncio.sleep(30)
```

- [ ] **Step 4: Update `make_status_command` in `bot/commands/usage.py`**

Replace `make_status_command` in `src/familylink_server/bot/commands/usage.py`:

```python
def make_status_command(
    service: FamilyLinkService,
    make_session: Callable[[], AbstractAsyncContextManager[AsyncSession]],
) -> app_commands.Command:
    """Factory: return a /status app_commands.Command bound to service and make_session."""

    @app_commands.command(
        name='status',
        description='Show a dashboard overview of all children and devices',
    )
    async def status(interaction: discord.Interaction) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                'You do not have permission to use this command.',
                ephemeral=True,
            )
            return
        members = await service.get_members()
        supervised = [
            m
            for m in members.members
            if m.member_supervision_info
            and m.member_supervision_info.is_supervised_member
        ]
        children_data = []
        for child in supervised:
            usage = await service.get_apps_and_usage(child.user_id)
            total = sum(getattr(a, 'usage_today_seconds', 0) or 0 for a in usage.apps)
            from familylink_server.bot.client import _fetch_linux_rows

            linux_rows = await _fetch_linux_rows(child.user_id, make_session)
            children_data.append({
                'name': child.profile.display_name,
                'total_seconds': total,
                'device_count': len(usage.device_info),
                'linux_machines': linux_rows,
            })
        from familylink_server.bot.embeds import status_embed

        embed = status_embed(children_data)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    return status
```

Add missing imports at the top of `bot/commands/usage.py`:

```python
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from familylink_server.bot.commands import (
    child_autocomplete,
    require_discord_role,
    resolve_child,
)
from familylink_server.bot.embeds import (
    status_embed,
    usage_history_embed,
    usage_today_embed,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession

    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService
```

- [ ] **Step 5: Update `main.py` — hoist notifier, pass to poller + bot**

Replace `src/familylink_server/main.py` lifespan with:

```python
@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize services at startup; shut down cleanly."""
    init_service()

    from familylink_server.db.session import make_session as _make_session

    notifier = None
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
            make_session=_make_session,
        )
        bot_task = asyncio.create_task(
            _bot_task_with_restart(bot, settings.discord_bot_token)  # type: ignore[arg-type]
        )
        logger.info('Discord bot task started')
    else:
        logger.info(
            'Discord bot disabled (DISCORD_BOT_TOKEN / GUILD_ID / CHANNEL_ID not set)'
        )

    poller_task = asyncio.create_task(poller_loop(notifier=notifier))
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

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/server/ -v
```

Expected: all PASSED. If `test_bot_commands.py` fails because `make_status_command` signature changed, update the call in that test to pass a dummy `make_session`.

- [ ] **Step 7: Run ruff**

```bash
ruff check src tests && ruff format src tests
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/familylink_server/bot/client.py \
        src/familylink_server/bot/commands/usage.py \
        src/familylink_server/main.py \
        tests/server/test_main.py
git commit -m 'feat: wire make_session and notifier into bot and poller'
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `bonus_mins` column + migration | Task 1 |
| `unlock_session` helper | Task 2 |
| Poller uses `effective_limit` | Task 3 |
| Poller notifies Discord on lock | Task 3 |
| Poller notifies Discord on poweroff | Task 3 |
| HTTP `/bonus` endpoint | Task 4 |
| Unlock if locked on bonus | Task 4 |
| Card bonus buttons (+15/+30/+60) | Task 4 |
| Progress bar uses `effective_limit_mins` | Task 4 |
| Dashboard Linux section (read-only) | Task 5 |
| `_ACTION_MAP` + embed extensions | Task 6 |
| `/status` shows Linux machines | Task 8 |
| Daily summary shows Linux machines | Task 8 |
| `/linux bonus` Discord command | Task 7 |
| `make_session` passed to bot | Task 8 |
| `notifier` passed to poller | Task 8 |

**Placeholder scan:** No TBDs or "implement later" phrases.

**Type consistency:**
- `_machine_context()` returns `effective_limit_mins` and `bonus_mins` — consumed by card partial and bonus endpoint.
- `poller_loop(notifier=None)` / `poll_machine(machine, notifier=None)` — consistent through Task 3 and Task 8.
- `make_status_command(service, make_session)` — two-arg signature produced in Task 8, called consistently.
- `_fetch_linux_rows(child_id, make_session)` helper defined in `bot/client.py` and imported in `bot/commands/usage.py`.
- `post_daily_summary(..., linux_machines=None)` — keyword arg added in Task 6, called in Task 8.
