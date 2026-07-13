# Auto-Block Overused Apps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Force-block a parent-selected app once its live usage crosses Google's own daily limit (which sometimes fails to enforce itself), auto-restore it the next day, and let a parent grant bonus minutes that raise the effective cap before the enforcer re-blocks again.

**Architecture:** A new asyncio background task (`app_enforcer_loop`, mirroring the existing `linux_poller.py` pattern) polls every 5 minutes, reads live per-app usage + limit from the Google Family Link API, and calls the existing `block_app`/`set_app_limit` client methods. Per-child, per-app opt-in and our own block bookkeeping live in a repurposed `AppConfig` table (currently unused). Two new HTMX endpoints on the existing `/apps` router let a parent toggle opt-in and grant bonus time.

**Tech Stack:** FastAPI, SQLAlchemy async (asyncpg), Alembic, Jinja2 + HTMX, pytest + pytest-asyncio (auto mode), unittest.mock (`AsyncMock`/`MagicMock`/`patch`).

## Global Constraints

- Poll interval is fixed at `POLL_INTERVAL = 300` seconds — not configurable.
- Bonus presets are exactly 15, 30, 60 minutes — no other values, no cap on how many times they stack in a day.
- `AppConfig` never stores or duplicates the daily limit minutes. The threshold is always read live from Google (`app.supervision_setting.usage_limit.daily_usage_limit_mins`) at poll/grant time.
- `FamilyLink.remove_app_limit()` must never be used to restore access — it sends the same payload as `block_app()`. Restoring must call `set_app_limit(package_name, minutes, child_id)`.
- No global/env predefined app list. Opt-in is per `(child_id, package_name)`, set via the web UI checkbox only.
- No Discord bot commands in this plan (web UI only).
- No notification to the child on block or bonus grant.

---

## Task 1: `AppConfig` schema — auto-block + bonus columns

**Files:**
- Modify: `src/familylink_server/db/models.py:22-38` (the `AppConfig` class)
- Create: `alembic/versions/004_auto_block_overused_apps.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `AppConfig` columns `auto_block_enabled: bool`, `auto_blocked_at: datetime | None`, `bonus_mins: int`, `bonus_date: date | None`, plus a unique constraint on `(child_id, package_name)`. All later tasks read/write these.

- [ ] **Step 1: Update the `AppConfig` model**

Replace the `AppConfig` class in `src/familylink_server/db/models.py` (currently lines 22-38) with:

```python
class AppConfig(Base):
    """App configuration settings for a child's device usage."""

    __tablename__ = 'app_configs'
    __table_args__ = (UniqueConstraint('child_id', 'package_name'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_name: Mapped[str] = mapped_column(String(256), nullable=False)
    package_name: Mapped[str] = mapped_column(String(256), nullable=False)
    max_mins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_mask: Mapped[str] = mapped_column(String(64), default='')
    time_range: Mapped[str] = mapped_column(String(32), default='')
    always_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    auto_block_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_blocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bonus_mins: Mapped[int] = mapped_column(Integer, default=0)
    bonus_date: Mapped[date | None] = mapped_column(Date, nullable=True)
```

`date` needs importing alongside the existing `datetime` import at the top of the file. Change:

```python
from datetime import UTC, date, datetime
```

(`Boolean`, `Date`, `DateTime`, `Integer`, `String`, `UniqueConstraint` are already imported in this file — no other import changes needed.)

- [ ] **Step 2: Write the migration**

Create `alembic/versions/004_auto_block_overused_apps.py`:

```python
"""add auto-block and bonus columns to app_configs

Revision ID: 004
Revises: 003
Create Date: 2026-07-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: str | Sequence[str] | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add auto_block_enabled, auto_blocked_at, bonus_mins, bonus_date to app_configs."""
    op.add_column(
        "app_configs",
        sa.Column(
            "auto_block_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "app_configs",
        sa.Column("auto_blocked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "app_configs",
        sa.Column("bonus_mins", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "app_configs",
        sa.Column("bonus_date", sa.Date(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_app_configs_child_package", "app_configs", ["child_id", "package_name"]
    )


def downgrade() -> None:
    """Drop auto-block and bonus columns from app_configs."""
    op.drop_constraint("uq_app_configs_child_package", "app_configs", type_="unique")
    op.drop_column("app_configs", "bonus_date")
    op.drop_column("app_configs", "bonus_mins")
    op.drop_column("app_configs", "auto_blocked_at")
    op.drop_column("app_configs", "auto_block_enabled")
```

- [ ] **Step 3: Verify the model imports cleanly**

Run: `python -c "from familylink_server.db.models import AppConfig; print(AppConfig.__table__.columns.keys())"`
Expected: prints a column list including `auto_block_enabled`, `auto_blocked_at`, `bonus_mins`, `bonus_date` — no import errors.

- [ ] **Step 4: Apply and verify the migration against the dev database**

Run: `alembic upgrade head`
Expected: completes with no errors, ends on revision `004`.

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: both complete with no errors — confirms `downgrade()` is correct and reversible.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/db/models.py alembic/versions/004_auto_block_overused_apps.py
git commit -m "feat: add auto-block and bonus columns to app_configs"
```

---

## Task 2: `FamilyLinkService.get_apps_and_usage` cache bypass

**Files:**
- Modify: `src/familylink_server/services/family_link.py:58-67`
- Test: `tests/server/test_family_link_service.py`

**Interfaces:**
- Consumes: nothing new (existing `FamilyLinkService` internals).
- Produces: `get_apps_and_usage(self, child_id: str, bypass_cache: bool = False) -> AppUsage`. Task 3's `enforce_child` calls this with `bypass_cache=True`.

- [ ] **Step 1: Write the failing test**

Add to `tests/server/test_family_link_service.py`:

```python
async def test_get_apps_and_usage_bypass_cache_ignores_fresh_cache(mock_client):
    """bypass_cache=True calls the client even when a fresh cache entry exists."""
    from familylink_server.services.family_link import FamilyLinkService

    svc = FamilyLinkService.__new__(FamilyLinkService)
    svc._client = mock_client
    svc._ttl = 900
    svc._usage_cache = {}

    await svc.get_apps_and_usage('child1')
    await svc.get_apps_and_usage('child1', bypass_cache=True)

    assert mock_client.get_apps_and_usage.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_family_link_service.py::test_get_apps_and_usage_bypass_cache_ignores_fresh_cache -v`
Expected: FAIL — `TypeError: get_apps_and_usage() got an unexpected keyword argument 'bypass_cache'`

- [ ] **Step 3: Implement `bypass_cache`**

In `src/familylink_server/services/family_link.py`, replace the `get_apps_and_usage` method (currently lines 58-67):

```python
    async def get_apps_and_usage(
        self, child_id: str, bypass_cache: bool = False
    ) -> AppUsage:
        """Return app usage for a child, using the cache when still fresh."""
        if not hasattr(self, '_usage_cache'):
            self._usage_cache: dict[str, tuple[AppUsage, datetime]] = {}
        if not bypass_cache:
            cached = self._usage_cache.get(child_id)
            if cached and self._is_fresh(cached[1]):
                return cached[0]
        result = await asyncio.to_thread(self._client.get_apps_and_usage, child_id)
        self._usage_cache[child_id] = (result, datetime.now(UTC))
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/server/test_family_link_service.py -v`
Expected: all PASS, including the new test.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/services/family_link.py tests/server/test_family_link_service.py
git commit -m "feat: add bypass_cache param to get_apps_and_usage"
```

---

## Task 3: `app_enforcer.enforce_child` — core enforcement logic

**Files:**
- Create: `src/familylink_server/services/app_enforcer.py`
- Test: `tests/server/test_app_enforcer.py`

**Interfaces:**
- Consumes: `AppConfig` columns from Task 1 (`child_id`, `package_name`, `auto_block_enabled`, `auto_blocked_at`, `bonus_mins`, `bonus_date`); `FamilyLinkService.get_apps_and_usage(child_id, bypass_cache=True)` from Task 2; `FamilyLinkService.block_app(package_name, child_id)`, `FamilyLinkService.set_app_limit(package_name, minutes, child_id)` (both pre-existing, unchanged); `familylink.models.App`/`AppUsage`/`AppUsageSession`; `familylink_server.db.session.make_session`; `familylink_server.db.models.AuditLog`.
- Produces: `enforce_child(child_id: str, svc: FamilyLinkService, notifier: DiscordNotifier | None = None) -> None`. Task 4's `app_enforcer_loop` calls this per child.

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_app_enforcer.py`:

```python
"""Tests for the app-overuse enforcer."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_config(
    package_name='com.example.app',
    auto_blocked_at=None,
    bonus_mins=0,
    bonus_date=None,
):
    cfg = MagicMock()
    cfg.package_name = package_name
    cfg.auto_blocked_at = auto_blocked_at
    cfg.bonus_mins = bonus_mins
    cfg.bonus_date = bonus_date
    return cfg


def _make_app(package_name='com.example.app', limit_mins=30):
    app = MagicMock()
    app.package_name = package_name
    app.supervision_setting.usage_limit = (
        MagicMock(daily_usage_limit_mins=limit_mins) if limit_mins is not None else None
    )
    return app


def _make_usage_session(package_name='com.example.app', usage_seconds=0.0, day_offset=0):
    d = datetime.date.today() + datetime.timedelta(days=day_offset)
    s = MagicMock()
    s.usage = str(usage_seconds)
    s.app_id.android_app_package_name = package_name
    s.date.year = d.year
    s.date.month = d.month
    s.date.day = d.day
    return s


def _make_usage(apps, sessions):
    u = MagicMock()
    u.apps = apps
    u.app_usage_sessions = sessions
    return u


def _make_session_ctx(configs):
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = configs
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx, mock_session


async def test_enforce_child_blocks_when_usage_exceeds_limit():
    """usage_mins >= limit and not yet blocked -> block_app is called and auto_blocked_at is set."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config()
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=30 * 60)],
    )
    mock_ctx, mock_session = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_awaited_once_with('com.example.app', 'child1')
    assert config.auto_blocked_at is not None
    mock_session.commit.assert_awaited_once()


async def test_enforce_child_does_not_block_when_under_limit():
    """usage_mins < limit -> block_app is not called."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config()
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=10 * 60)],
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_not_awaited()
    assert config.auto_blocked_at is None


async def test_enforce_child_skips_when_no_google_limit():
    """App has no usage_limit configured in Google -> nothing happens."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config()
    usage = _make_usage(
        [_make_app(limit_mins=None)],
        [_make_usage_session(usage_seconds=999 * 60)],
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_not_awaited()


async def test_enforce_child_restores_after_midnight():
    """auto_blocked_at from a previous day -> set_app_limit restores, auto_blocked_at clears."""
    from familylink_server.services.app_enforcer import enforce_child

    yesterday = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    config = _make_config(auto_blocked_at=yesterday)
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=0)],
    )
    mock_ctx, mock_session = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.set_app_limit = AsyncMock()
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.set_app_limit.assert_awaited_once_with('com.example.app', 30, 'child1')
    assert config.auto_blocked_at is None
    mock_svc.block_app.assert_not_awaited()
    mock_session.commit.assert_awaited_once()


async def test_enforce_child_idempotent_when_already_blocked_today():
    """auto_blocked_at set today, still over limit -> block_app is not called again."""
    from familylink_server.services.app_enforcer import enforce_child

    now = datetime.datetime.now(datetime.UTC)
    config = _make_config(auto_blocked_at=now)
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=45 * 60)],
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_not_awaited()


async def test_enforce_child_bonus_raises_effective_limit():
    """bonus_mins granted today keeps the app unblocked past the base limit."""
    from familylink_server.services.app_enforcer import enforce_child

    today = datetime.date.today()
    config = _make_config(bonus_mins=15, bonus_date=today)
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=40 * 60)],  # 40 min: over base 30, under 30+15
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_not_awaited()


async def test_enforce_child_reblocks_after_bonus_exceeded():
    """Usage crosses base limit + bonus -> block_app is called using the raised threshold."""
    from familylink_server.services.app_enforcer import enforce_child

    today = datetime.date.today()
    config = _make_config(bonus_mins=15, bonus_date=today)
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=45 * 60)],  # 45 min >= 30+15
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    mock_svc.block_app.assert_awaited_once_with('com.example.app', 'child1')
    assert config.auto_blocked_at is not None


async def test_enforce_child_sums_multiple_sessions_same_day_ignores_other_days():
    """Usage from two devices today is summed; a session from a different day is ignored."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config()
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [
            _make_usage_session(usage_seconds=10 * 60),
            _make_usage_session(usage_seconds=25 * 60),
            _make_usage_session(usage_seconds=999 * 60, day_offset=-1),
        ],
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)

    # 10 + 25 = 35 min >= 30 min limit -> blocks; the 999-min session from yesterday is excluded
    mock_svc.block_app.assert_awaited_once_with('com.example.app', 'child1')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_app_enforcer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'familylink_server.services.app_enforcer'`

- [ ] **Step 3: Implement `app_enforcer.py`**

Create `src/familylink_server/services/app_enforcer.py`:

```python
"""Background asyncio task that force-blocks apps Google fails to enforce daily limits on."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from familylink_server.db.models import AppConfig, AuditLog
from familylink_server.db.session import make_session

if TYPE_CHECKING:
    from familylink.models import AppUsage
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

logger = logging.getLogger(__name__)

POLL_INTERVAL = 300


def _usage_minutes_by_package(usage: AppUsage, today: date) -> dict[str, float]:
    """Sum today's per-package usage, in minutes, from raw usage sessions."""
    totals: dict[str, float] = {}
    for session in usage.app_usage_sessions:
        if (session.date.year, session.date.month, session.date.day) != (
            today.year,
            today.month,
            today.day,
        ):
            continue
        package = session.app_id.android_app_package_name
        totals[package] = totals.get(package, 0.0) + float(session.usage) / 60
    return totals


async def enforce_child(
    child_id: str,
    svc: FamilyLinkService,
    notifier: DiscordNotifier | None = None,
) -> None:
    """Block/restore one child's opted-in apps based on live Google usage vs. limit."""
    today = date.today()
    async with make_session() as session:
        result = await session.execute(
            select(AppConfig).where(
                AppConfig.child_id == child_id,
                AppConfig.auto_block_enabled.is_(True),
            )
        )
        configs = result.scalars().all()
        if not configs:
            return

        usage = await svc.get_apps_and_usage(child_id, bypass_cache=True)
        usage_by_package = _usage_minutes_by_package(usage, today)
        apps_by_package = {a.package_name: a for a in usage.apps}

        for config in configs:
            app = apps_by_package.get(config.package_name)
            if app is None or app.supervision_setting.usage_limit is None:
                continue
            limit_mins = app.supervision_setting.usage_limit.daily_usage_limit_mins

            if (
                config.auto_blocked_at is not None
                and config.auto_blocked_at.date() < today
            ):
                await svc.set_app_limit(config.package_name, limit_mins, child_id)
                config.auto_blocked_at = None
                session.add(
                    AuditLog(
                        child_id=child_id,
                        action='auto_unblock',
                        target=config.package_name,
                        new_value=f'{limit_mins} min',
                        occurred_at=datetime.now(UTC),
                    )
                )
                if notifier:
                    await notifier.notify_change(
                        'auto_unblock', child_id, config.package_name, 'enforcer'
                    )
                continue

            bonus = config.bonus_mins if config.bonus_date == today else 0
            effective_limit = limit_mins + bonus
            usage_mins = usage_by_package.get(config.package_name, 0.0)

            if usage_mins >= effective_limit and config.auto_blocked_at is None:
                await svc.block_app(config.package_name, child_id)
                config.auto_blocked_at = datetime.now(UTC)
                session.add(
                    AuditLog(
                        child_id=child_id,
                        action='auto_block',
                        target=config.package_name,
                        new_value=f'{usage_mins:.0f}/{effective_limit} min',
                        occurred_at=datetime.now(UTC),
                    )
                )
                if notifier:
                    await notifier.notify_change(
                        'auto_block', child_id, config.package_name, 'enforcer'
                    )

        await session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_app_enforcer.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/services/app_enforcer.py tests/server/test_app_enforcer.py
git commit -m "feat: add app overuse enforcement logic"
```

---

## Task 4: `app_enforcer_loop` + `main.py` wiring

**Files:**
- Modify: `src/familylink_server/services/app_enforcer.py` (append `app_enforcer_loop`)
- Modify: `src/familylink_server/main.py:1-37` (imports), `:97-147` (lifespan)
- Test: `tests/server/test_app_enforcer.py` (append one test)

**Interfaces:**
- Consumes: `enforce_child` from Task 3; `familylink_server.services.family_link.get_service`.
- Produces: `app_enforcer_loop(svc: FamilyLinkService, notifier: DiscordNotifier | None = None) -> None`, started/stopped in `main.py`'s `lifespan`.

- [ ] **Step 1: Write the failing test**

Append to `tests/server/test_app_enforcer.py`:

```python
import asyncio

import pytest


async def test_app_enforcer_loop_calls_enforce_child_for_each_distinct_child():
    """The loop queries distinct opted-in child_ids and enforces each one."""
    from familylink_server.services import app_enforcer

    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = ['child1', 'child2']
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_enforce = AsyncMock()
    mock_svc = MagicMock()

    async def _raise_cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    with (
        patch(
            'familylink_server.services.app_enforcer.make_session',
            return_value=mock_ctx,
        ),
        patch('familylink_server.services.app_enforcer.enforce_child', mock_enforce),
        patch(
            'familylink_server.services.app_enforcer.asyncio.sleep',
            side_effect=_raise_cancelled,
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await app_enforcer.app_enforcer_loop(mock_svc)

    mock_enforce.assert_any_await('child1', mock_svc, notifier=None)
    mock_enforce.assert_any_await('child2', mock_svc, notifier=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_app_enforcer.py::test_app_enforcer_loop_calls_enforce_child_for_each_distinct_child -v`
Expected: FAIL — `AttributeError: module 'familylink_server.services.app_enforcer' has no attribute 'app_enforcer_loop'`

- [ ] **Step 3: Implement `app_enforcer_loop`**

Append to `src/familylink_server/services/app_enforcer.py` (add `import asyncio` to the existing imports at the top, alongside `import logging`):

```python
import asyncio
import logging
```

Then append at the end of the file:

```python
async def app_enforcer_loop(
    svc: FamilyLinkService, notifier: DiscordNotifier | None = None
) -> None:
    """Iterate every child with at least one auto-block-enabled app, every POLL_INTERVAL."""
    while True:
        try:
            async with make_session() as session:
                result = await session.execute(
                    select(AppConfig.child_id)
                    .where(AppConfig.auto_block_enabled.is_(True))
                    .distinct()
                )
                child_ids = result.scalars().all()

            await asyncio.gather(
                *[
                    enforce_child(child_id, svc, notifier=notifier)
                    for child_id in child_ids
                ],
                return_exceptions=True,
            )
        except Exception:
            logger.exception('App enforcer cycle failed')
        await asyncio.sleep(POLL_INTERVAL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_app_enforcer.py -v`
Expected: all PASS.

- [ ] **Step 5: Wire into `main.py`**

In `src/familylink_server/main.py`, add the import next to the existing poller import (line 34):

```python
from familylink_server.services.app_enforcer import app_enforcer_loop
from familylink_server.services.linux_poller import poller_loop
```

In `lifespan()`, after the existing poller startup block (currently lines 127-128):

```python
    poller_task = asyncio.create_task(poller_loop(notifier=notifier))
    logger.info('Linux machine poller started')

    enforcer_task = asyncio.create_task(
        app_enforcer_loop(get_service(), notifier=notifier)
    )
    logger.info('App overuse enforcer started')
```

And in the shutdown section, after the existing poller cleanup (currently lines 135-137):

```python
    poller_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller_task

    enforcer_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await enforcer_task
```

- [ ] **Step 6: Verify the app still starts**

Run: `python -c "from familylink_server.main import app; print('ok')"`
Expected: prints `ok` — no import errors from the new wiring.

- [ ] **Step 7: Commit**

```bash
git add src/familylink_server/services/app_enforcer.py src/familylink_server/main.py tests/server/test_app_enforcer.py
git commit -m "feat: start app overuse enforcer background task"
```

---

## Task 5: Auto-block opt-in — `/apps` page context + `/auto-block` endpoint + checkbox

**Files:**
- Modify: `src/familylink_server/routers/apps.py` (imports, `apps_page`, `set_limit`, new `_get_or_create_app_config` helper, new `set_auto_block` endpoint)
- Modify: `src/familylink_server/templates/partials/app_row.html`
- Test: `tests/server/test_routers_apps.py` (fix 6 existing tests + extend `test_set_limit_returns_partial` + add new tests)

**Interfaces:**
- Consumes: `AppConfig` from Task 1; `get_session` (pre-existing FastAPI dependency).
- Produces: `_get_or_create_app_config(session, child_id, package_name) -> AppConfig`, reused by Task 6's bonus endpoint. `POST /apps/{package}/auto-block` endpoint.

- [ ] **Step 1: Update imports in `apps.py`**

Change the top of `src/familylink_server/routers/apps.py`:

```python
"""Router for the /apps HTML page and HTMX limit/block/allow endpoints."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.constants import CHILD_COLORS
from familylink_server.db import AppConfig, AuditLog, get_session
from familylink_server.services.discord_notifier import get_notifier
from familylink_server.services.family_link import FamilyLinkService, get_service
```

(This adds `select`, `IntegrityError`, and `AppConfig` to the existing imports.)

- [ ] **Step 2: Add the get-or-create helper**

Add after `_app_state` (currently ending at line 50) and before `apps_page`:

```python
async def _get_or_create_app_config(
    session: AsyncSession, child_id: str, package_name: str
) -> AppConfig:
    """Get the AppConfig row for (child_id, package_name), creating it if absent."""
    stmt = select(AppConfig).where(
        AppConfig.child_id == child_id, AppConfig.package_name == package_name
    )
    config = (await session.execute(stmt)).scalar_one_or_none()
    if config is None:
        config = AppConfig(
            child_id=child_id, app_name=package_name, package_name=package_name
        )
        session.add(config)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            config = (await session.execute(stmt)).scalar_one()
    return config
```

- [ ] **Step 3: Update `apps_page` to include auto-block state**

Replace the `apps_page` function (currently lines 53-102) with:

```python
@router.get('/apps', response_class=HTMLResponse)
async def apps_page(
    request: Request,
    filter: str = 'all',
    child: str = '',
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Render the apps page with a per-child tab strip and inline edit controls."""
    members = await svc.get_members()
    supervised = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    children = [
        {
            'user_id': m.user_id,
            'display_name': m.profile.display_name,
            'color': CHILD_COLORS[i % len(CHILD_COLORS)],
        }
        for i, m in enumerate(supervised)
    ]

    child_ids = {c['user_id'] for c in children}
    active_child_id = (
        child if child in child_ids else (children[0]['user_id'] if children else '')
    )

    apps = []
    if active_child_id:
        usage = await svc.get_apps_and_usage(active_child_id)
        result = await session.execute(
            select(AppConfig).where(AppConfig.child_id == active_child_id)
        )
        configs_by_package = {c.package_name: c for c in result.scalars().all()}
        for a in sorted(usage.apps, key=lambda x: x.title.lower()):
            config = configs_by_package.get(a.package_name)
            apps.append(
                dict(
                    _app_state(a),
                    child_id=active_child_id,
                    auto_block_enabled=config.auto_block_enabled if config else False,
                    auto_blocked_at=config.auto_blocked_at if config else None,
                )
            )
        if filter != 'all':
            apps = [a for a in apps if a['state'] == filter]

    return templates.TemplateResponse(
        request,
        'apps.html',
        {
            'apps': apps,
            'children': children,
            'active_child_id': active_child_id,
            'filter': filter,
            'auth_failed': svc.auth_failed,
        },
    )
```

- [ ] **Step 4: Update `set_limit` to preserve auto-block state in its response**

In the existing `set_limit` endpoint (currently lines 105-143), add a config lookup before building `app_data`, and add the two new keys. Replace:

```python
    session.add(
        AuditLog(
            child_id=child_id,
            action='set_limit',
            target=package,
            new_value=str(minutes),
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'limited',
        'state_label': f'Limited {minutes} min',
        'limit_mins': minutes,
        'child_id': child_id,
    }
```

with:

```python
    session.add(
        AuditLog(
            child_id=child_id,
            action='set_limit',
            target=package,
            new_value=str(minutes),
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    config_result = await session.execute(
        select(AppConfig).where(
            AppConfig.child_id == child_id, AppConfig.package_name == package
        )
    )
    config = config_result.scalar_one_or_none()
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'limited',
        'state_label': f'Limited {minutes} min',
        'limit_mins': minutes,
        'child_id': child_id,
        'auto_block_enabled': config.auto_block_enabled if config else False,
        'auto_blocked_at': config.auto_blocked_at if config else None,
    }
```

- [ ] **Step 5: Add the `/auto-block` endpoint**

Add at the end of `apps.py`, after the `allow_app` endpoint:

```python
@router.post('/apps/{package}/auto-block', response_class=HTMLResponse)
async def set_auto_block(
    package: str,
    request: Request,
    child_id: str = Form(...),
    limit_mins: int = Form(...),
    enabled: bool = Form(False),
    _email: str = require_user,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Toggle auto-block-on-overuse opt-in for an app and return the updated row partial."""
    config = await _get_or_create_app_config(session, child_id, package)
    config.auto_block_enabled = enabled
    session.add(
        AuditLog(
            child_id=child_id,
            action='auto_block_toggle',
            target=package,
            new_value=str(enabled),
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'limited',
        'state_label': f'Limited {limit_mins} min',
        'limit_mins': limit_mins,
        'child_id': child_id,
        'auto_block_enabled': config.auto_block_enabled,
        'auto_blocked_at': None,
    }
    return templates.TemplateResponse(
        request, 'partials/app_row.html', {'app': app_data}
    )
```

- [ ] **Step 6: Add the checkbox to `app_row.html`**

Replace `src/familylink_server/templates/partials/app_row.html` in full:

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
    {% if app.state == "limited" %}
      <form hx-post="/apps/{{ app.package_name }}/auto-block"
            hx-trigger="change"
            hx-target="#row-{{ app.package_name | replace('.', '-') }}"
            hx-swap="outerHTML" style="display:inline">
        <input type="hidden" name="child_id" value="{{ app.child_id }}">
        <input type="hidden" name="limit_mins" value="{{ app.limit_mins }}">
        <label style="font-size:0.75rem">
          <input type="checkbox" name="enabled" value="true" {{ 'checked' if app.auto_block_enabled }}>
          Auto-block on overuse
        </label>
      </form>
    {% endif %}
    {% if app.auto_blocked_at %}
      <form hx-post="/apps/{{ app.package_name }}/bonus"
            hx-target="#row-{{ app.package_name | replace('.', '-') }}"
            hx-swap="outerHTML" style="display:inline">
        <input type="hidden" name="child_id" value="{{ app.child_id }}">
        {% for mins in [15, 30, 60] %}
          <button type="submit" name="minutes" value="{{ mins }}" class="outline" style="font-size:0.75rem;padding:0.25rem 0.5rem">+{{ mins }} min</button>
        {% endfor %}
      </form>
    {% endif %}
  </td>
</tr>
```

- [ ] **Step 7: Fix the 6 existing GET /apps tests**

`session.execute` is now called inside `apps_page()`, so every test that overrides `get_service` but not `get_session` will hit a real `TypeError` awaiting a real (unmocked) DB session. In `tests/server/test_routers_apps.py`, add this helper near the top (after `_make_client`):

```python
def _empty_config_session():
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    return mock_session
```

Then update each of these 6 test functions to add a `get_session` override. For `test_apps_page_returns_200`:

```python
def test_apps_page_returns_200():
    """GET /apps with a valid session returns 200 and app titles."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(
            members=[
                MagicMock(
                    user_id='child1',
                    member_supervision_info=MagicMock(is_supervised_member=True),
                )
            ]
        )
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=MagicMock(
            apps=[
                _make_app_mock('YouTube', 'com.google.android.youtube', limit_mins=30)
            ],
            device_info=[],
            app_usage_sessions=[],
        )
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: _empty_config_session()
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'YouTube' in resp.text
```

Apply the identical pattern (add `app.dependency_overrides[get_session] = lambda: _empty_config_session()` before the `try:`, and `app.dependency_overrides.pop(get_session, None)` in the `finally:`) to:
- `test_apps_page_shows_child_tabs_for_multiple_children`
- `test_apps_page_child_param_selects_correct_child`
- `test_apps_page_invalid_child_falls_back_to_first`
- `test_apps_page_single_child_no_tab_links`
- `test_apps_page_kid_switcher_shows_avatar`

- [ ] **Step 8: Fix `test_set_limit_returns_partial`**

`set_limit` now also calls `session.execute`. Update the test's `mock_session` construction:

```python
def test_set_limit_returns_partial(monkeypatch):
    """POST /apps/{package}/limit calls set_app_limit with int minutes and returns 200."""
    mock_svc = MagicMock()
    mock_svc.set_app_limit = AsyncMock(return_value=None)
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/limit',
            data={'child_id': 'child1', 'minutes': '45'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    mock_svc.set_app_limit.assert_called_once_with(
        'com.google.android.youtube', 45, child_id='child1'
    )
```

- [ ] **Step 9: Write new tests for the checkbox and the `/auto-block` endpoint**

Add to `tests/server/test_routers_apps.py`:

```python
def test_apps_page_shows_auto_block_checkbox_for_limited_app():
    """A 'limited' app row includes the auto-block checkbox, checked when opted in."""
    from familylink_server.db.models import AppConfig

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(members=[_make_member('child1', 'Emma')])
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube', limit_mins=30)
        )
    )
    config = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = [config]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Auto-block on overuse' in resp.text
    assert 'checked' in resp.text


def test_apps_page_hides_auto_block_checkbox_for_blocked_app():
    """A 'blocked' app row does not include the auto-block checkbox."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(members=[_make_member('child1', 'Emma')])
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube', hidden=True)
        )
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: _empty_config_session()
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Auto-block on overuse' not in resp.text


def test_set_auto_block_enables_creates_new_appconfig_row():
    """POST /apps/{package}/auto-block with enabled=true creates a row and returns 200."""
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    from familylink_server.main import app

    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/auto-block',
            data={'child_id': 'child1', 'limit_mins': '30', 'enabled': 'true'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'checked' in resp.text
    mock_session.commit.assert_awaited_once()


def test_set_auto_block_disables_existing_row():
    """POST with enabled omitted (unchecked) clears the opt-in flag on an existing row."""
    from familylink_server.db.models import AppConfig

    existing = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = existing
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    from familylink_server.main import app

    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/auto-block',
            data={'child_id': 'child1', 'limit_mins': '30'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert existing.auto_block_enabled is False
```

- [ ] **Step 10: Run all apps router tests**

Run: `python -m pytest tests/server/test_routers_apps.py -v`
Expected: all PASS (existing + new tests).

- [ ] **Step 11: Commit**

```bash
git add src/familylink_server/routers/apps.py src/familylink_server/templates/partials/app_row.html tests/server/test_routers_apps.py
git commit -m "feat: add auto-block opt-in checkbox to /apps"
```

---

## Task 6: Bonus time — `/bonus` endpoint + buttons

**Files:**
- Modify: `src/familylink_server/routers/apps.py` (import `date`, new `grant_bonus` endpoint)
- Test: `tests/server/test_routers_apps.py`

**Interfaces:**
- Consumes: `_get_or_create_app_config` from Task 5; `AppConfig.bonus_mins`/`bonus_date`/`auto_blocked_at` from Task 1; `FamilyLinkService.get_apps_and_usage`/`set_app_limit` (pre-existing).
- Produces: `POST /apps/{package}/bonus` endpoint. Nothing downstream consumes this — last task.

- [ ] **Step 1: Add the `date` import**

In `src/familylink_server/routers/apps.py`, change:

```python
from datetime import UTC, datetime
```

to:

```python
from datetime import UTC, date, datetime
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/server/test_routers_apps.py`:

```python
def test_grant_bonus_unblocks_auto_blocked_app():
    """POST /apps/{package}/bonus on an auto-blocked app calls set_app_limit and clears auto_blocked_at."""
    import datetime as dt

    from familylink_server.db.models import AppConfig

    existing = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
        auto_blocked_at=dt.datetime.now(dt.UTC),
        bonus_mins=0,
        bonus_date=None,
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = existing
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube', limit_mins=30)
        )
    )
    mock_svc.set_app_limit = AsyncMock()

    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/bonus',
            data={'child_id': 'child1', 'minutes': '15'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 200
    mock_svc.set_app_limit.assert_awaited_once_with(
        'com.google.android.youtube', 45, 'child1'
    )
    assert existing.auto_blocked_at is None
    assert existing.bonus_mins == 15


def test_grant_bonus_stacks_within_same_day():
    """A second bonus grant on the same day adds to bonus_mins instead of resetting it."""
    import datetime as dt

    from familylink_server.db.models import AppConfig

    today = dt.date.today()
    existing = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
        auto_blocked_at=None,
        bonus_mins=15,
        bonus_date=today,
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = existing
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=_make_usage())
    mock_svc.set_app_limit = AsyncMock()

    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/bonus',
            data={'child_id': 'child1', 'minutes': '30'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 200
    assert existing.bonus_mins == 45  # 15 + 30, not reset
    mock_svc.set_app_limit.assert_not_awaited()  # not currently auto-blocked


def test_grant_bonus_resets_on_new_day():
    """A bonus grant on a new day starts fresh instead of adding to yesterday's leftover."""
    import datetime as dt

    from familylink_server.db.models import AppConfig

    yesterday = dt.date.today() - dt.timedelta(days=1)
    existing = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
        auto_blocked_at=None,
        bonus_mins=15,
        bonus_date=yesterday,
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = existing
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=_make_usage())
    mock_svc.set_app_limit = AsyncMock()

    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/bonus',
            data={'child_id': 'child1', 'minutes': '30'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 200
    assert existing.bonus_mins == 30  # fresh start, not 15 + 30
    assert existing.bonus_date == dt.date.today()


def test_apps_page_shows_bonus_buttons_only_when_auto_blocked():
    """Bonus buttons appear on an auto-blocked row and not otherwise."""
    from familylink_server.db.models import AppConfig

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(members=[_make_member('child1', 'Emma')])
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube', hidden=True)
        )
    )
    import datetime as dt

    config = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
        auto_blocked_at=dt.datetime.now(dt.UTC),
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = [config]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert '+15 min' in resp.text
    assert '+30 min' in resp.text
    assert '+60 min' in resp.text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_routers_apps.py -k bonus -v`
Expected: FAIL — `404 Not Found` (endpoint doesn't exist yet) / assertion failures on missing bonus button text.

- [ ] **Step 4: Implement the `/bonus` endpoint**

Add to `src/familylink_server/routers/apps.py`, after the `set_auto_block` endpoint:

```python
@router.post('/apps/{package}/bonus', response_class=HTMLResponse)
async def grant_bonus(
    package: str,
    request: Request,
    child_id: str = Form(...),
    minutes: int = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Grant bonus minutes to an auto-blocked app, unblocking it immediately."""
    config = await _get_or_create_app_config(session, child_id, package)
    today = date.today()
    if config.bonus_date != today:
        config.bonus_mins = minutes
        config.bonus_date = today
    else:
        config.bonus_mins += minutes

    if config.auto_blocked_at is not None:
        usage = await svc.get_apps_and_usage(child_id)
        app_match = next((a for a in usage.apps if a.package_name == package), None)
        base_limit = (
            app_match.supervision_setting.usage_limit.daily_usage_limit_mins
            if app_match is not None and app_match.supervision_setting.usage_limit
            else 0
        )
        new_limit = base_limit + config.bonus_mins
        await svc.set_app_limit(package, new_limit, child_id)
        config.auto_blocked_at = None
        state, state_label, limit_mins = (
            'limited',
            f'Limited {new_limit} min',
            new_limit,
        )
    else:
        state, state_label, limit_mins = 'blocked', 'Blocked', None

    session.add(
        AuditLog(
            child_id=child_id,
            action='bonus_app',
            target=package,
            new_value=str(minutes),
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()

    app_data = {
        'package_name': package,
        'title': package,
        'state': state,
        'state_label': state_label,
        'limit_mins': limit_mins,
        'child_id': child_id,
        'auto_block_enabled': config.auto_block_enabled,
        'auto_blocked_at': config.auto_blocked_at,
    }
    return templates.TemplateResponse(
        request, 'partials/app_row.html', {'app': app_data}
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_routers_apps.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full server test suite**

Run: `python -m pytest tests/server/ -v`
Expected: all PASS — confirms nothing else in the server suite regressed.

- [ ] **Step 7: Lint and type-check**

Run: `ruff check src tests && ruff format --check src tests && mypy src`
Expected: no errors. Fix any issues (e.g. line length, unused imports) and re-run.

- [ ] **Step 8: Commit**

```bash
git add src/familylink_server/routers/apps.py tests/server/test_routers_apps.py
git commit -m "feat: add bonus-time grant endpoint and buttons"
```

---

## Self-Review Notes

- **Spec coverage:** Data Model (Task 1), Enforcement Logic (Task 3+4), Service Change (Task 2), Wiring (Task 4), Web UI checkbox (Task 5), Bonus time (Task 6), `remove_app_limit` avoidance (honored throughout — only `set_app_limit`/`block_app` are called), Error handling (try/except in `app_enforcer_loop`, idempotent block-trigger check covered by Task 3 test) — all spec sections have a corresponding task.
- **Fix included beyond the spec's literal text:** the spec's `Files Changed` table didn't call out that adding a DB session to `apps_page()` and a DB lookup to `set_limit()` would break 7 existing tests — Task 5 Steps 7-8 fix all of them as part of the same deliverable, since the feature can't ship with a broken existing test suite.
