# ntfy Kid Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push a notification to each kid's phone via ntfy when new homework is ingested, or when their remaining app/device time drops below 15 minutes.

**Architecture:** A new `NtfyNotifier` service, shaped exactly like the existing `DiscordNotifier` singleton (`services/discord_notifier.py`), sends JSON-body POSTs to a configurable ntfy server (self-hosted intranet instance) on a per-kid topic. It's wired into the two places that already compute "remaining time" — `app_enforcer.py` (Google app limits) and `linux_poller.py` (Linux machine limits) — as a new threshold check that fires once per day/session, and into the existing homework-ingest endpoint (`routers/homework.py`), which already distinguishes new vs. refreshed entries at the DB layer.

**Tech Stack:** FastAPI, SQLAlchemy async + Alembic, `httpx` (already a dependency), `pytest` + `pytest-httpx` for tests.

**Spec:** No separate spec file — this is a bounded extension of an existing pattern (Discord notifier). The design was proposed and approved in chat; see conversation history for the brainstorming/clarifying-questions record. Approved decisions baked into this plan:
- ntfy server: self-hosted intranet instance at `http://ntfy-qs0o4os08kggkcgs4kos4sgk.192.168.0.22.sslip.io` (configurable via `NTFY_BASE_URL`, not hardcoded), JSON publish API (not per-kid headers — the header API can't safely carry UTF-8/emoji titles).
- Low-time warning fires for both Google apps and Linux machines.
- Threshold: 15 minutes remaining.
- One ntfy topic per kid (`child_id → topic` mapping via a new env var).

## Global Constraints

- Python 3.12, `pip`/`python -m pytest` only — never `uv`.
- Ruff: Google docstring convention, single-quoted strings, isort-ordered imports.
- `asyncio_mode = "auto"` — `async def test_*` needs no `@pytest.mark.asyncio` decorator (existing tests use it inconsistently; match the file you're editing).
- New DB columns go through Alembic (`alembic/versions/`), following the numbered-file convention (`008_...`).
- Follow the exact singleton shape of `services/discord_notifier.py` (`init_notifier`/`get_notifier`, module-level `_notifier`).

---

### Task 1: `ntfy_topics` setting

**Files:**
- Modify: `src/familylink_server/config.py`
- Test: `tests/server/test_config.py`

**Interfaces:**
- Produces: `Settings.ntfy_topics: str` (raw env value), `Settings.ntfy_topics_parsed -> dict[str, str]` (parsed `child_id → topic` map), `Settings.ntfy_base_url: str` (ntfy server base URL). All consumed by Task 2/7.

- [ ] **Step 1: Write the failing tests**

Append to `tests/server/test_config.py`:

```python
def test_ntfy_topics_defaults_empty():
    """No NTFY_TOPICS set -> empty mapping.

    _env_file=None bypasses the developer's local .env — see
    test_discord_disabled_by_default for why that matters here.
    """
    from familylink_server.config import Settings

    s = Settings(_env_file=None)
    assert s.ntfy_topics_parsed == {}


def test_ntfy_topics_parses_single_pair(monkeypatch):
    monkeypatch.setenv('NTFY_TOPICS', 'child1:familylink-child1-abc123')

    from familylink_server.config import Settings

    s = Settings()
    assert s.ntfy_topics_parsed == {'child1': 'familylink-child1-abc123'}


def test_ntfy_topics_parses_multiple_pairs(monkeypatch):
    monkeypatch.setenv(
        'NTFY_TOPICS', 'child1:topic-one, child2:topic-two'
    )

    from familylink_server.config import Settings

    s = Settings()
    assert s.ntfy_topics_parsed == {
        'child1': 'topic-one',
        'child2': 'topic-two',
    }


def test_ntfy_topics_skips_malformed_entries(monkeypatch):
    """Entries without a ':' or with an empty side are dropped, not crashed on."""
    monkeypatch.setenv(
        'NTFY_TOPICS', 'child1:topic-one,garbage,child2:,:orphan-topic'
    )

    from familylink_server.config import Settings

    s = Settings()
    assert s.ntfy_topics_parsed == {'child1': 'topic-one'}


def test_ntfy_base_url_defaults_to_intranet_instance():
    """_env_file=None bypasses the developer's local .env, same reasoning as
    test_discord_disabled_by_default.
    """
    from familylink_server.config import Settings

    s = Settings(_env_file=None)
    assert (
        s.ntfy_base_url
        == 'http://ntfy-qs0o4os08kggkcgs4kos4sgk.192.168.0.22.sslip.io'
    )


def test_ntfy_base_url_overridable(monkeypatch):
    monkeypatch.setenv('NTFY_BASE_URL', 'https://ntfy.example.com')

    from familylink_server.config import Settings

    s = Settings()
    assert s.ntfy_base_url == 'https://ntfy.example.com'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_config.py -k ntfy_topics -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'ntfy_topics_parsed'`

- [ ] **Step 3: Implement**

In `src/familylink_server/config.py`, add the field next to the other Discord/eKRÉTA settings, and the parsing property next to `discord_summary_time_parsed`:

```python
    ntfy_topics: str = ''
    ntfy_base_url: str = 'http://ntfy-qs0o4os08kggkcgs4kos4sgk.192.168.0.22.sslip.io'
```

```python
    @property
    def ntfy_topics_parsed(self) -> dict[str, str]:
        """Parse 'child_id:topic,child_id:topic' into a dict, skipping malformed pairs."""
        result: dict[str, str] = {}
        for pair in self.ntfy_topics.split(','):
            pair = pair.strip()
            if ':' not in pair:
                continue
            child_id, topic = (part.strip() for part in pair.split(':', 1))
            if child_id and topic:
                result[child_id] = topic
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_config.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/config.py tests/server/test_config.py
git commit -m "feat: add NTFY_TOPICS/NTFY_BASE_URL settings for ntfy notifications

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: `NtfyNotifier` service

**Files:**
- Create: `src/familylink_server/services/ntfy_notifier.py`
- Test: `tests/server/test_ntfy_notifier.py`

**Interfaces:**
- Consumes: `Settings.ntfy_base_url` from Task 1 (plain `httpx.AsyncClient`).
- Produces: `NtfyNotifier(topics: dict[str, str], base_url: str)` with `async send(child_id, title, message, priority='default', tags=None)`, `async notify_homework(child_id, subject, deadline)`, `async notify_low_time(child_id, target_name, remaining_mins)`; module functions `init_notifier(topics: dict[str, str], base_url: str) -> NtfyNotifier` and `get_notifier() -> NtfyNotifier | None`. Consumed by Task 4 (`app_enforcer.py`), Task 5 (`linux_poller.py`), Task 6 (`routers/homework.py`), Task 7 (`main.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_ntfy_notifier.py`:

```python
"""Tests for NtfyNotifier service."""

from unittest.mock import AsyncMock

import pytest

TEST_BASE_URL = 'http://ntfy-qs0o4os08kggkcgs4kos4sgk.192.168.0.22.sslip.io'


@pytest.fixture()
def notifier():
    """Create a test notifier with one mapped kid."""
    from familylink_server.services.ntfy_notifier import NtfyNotifier

    return NtfyNotifier(
        topics={'child1': 'familylink-child1-abc123'}, base_url=TEST_BASE_URL
    )


async def test_send_no_op_for_unmapped_child(notifier, httpx_mock):
    """No topic mapped for this child_id -> no HTTP call is made."""
    await notifier.send('child-unknown', 'Title', 'Message')
    assert len(httpx_mock.get_requests()) == 0


async def test_send_posts_json_payload_to_ntfy(notifier, httpx_mock):
    httpx_mock.add_response(url=TEST_BASE_URL, method='POST')
    await notifier.send('child1', 'Hello', 'World', priority='high', tags=['book'])

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    body = requests[0].read()
    import json

    payload = json.loads(body)
    assert payload == {
        'topic': 'familylink-child1-abc123',
        'title': 'Hello',
        'message': 'World',
        'priority': 'high',
        'tags': ['book'],
    }


async def test_send_swallows_http_errors(notifier, httpx_mock):
    """A failed ntfy push must not raise — it's best-effort."""
    httpx_mock.add_response(url=TEST_BASE_URL, method='POST', status_code=500)
    await notifier.send('child1', 'Hello', 'World')  # must not raise


async def test_notify_homework_calls_send_with_expected_args(notifier):
    notifier.send = AsyncMock()
    await notifier.notify_homework('child1', 'Matek', '2026-09-15')
    notifier.send.assert_awaited_once_with(
        'child1',
        title='📚 New homework — Matek',
        message='Due 2026-09-15',
        tags=['book'],
    )


async def test_notify_low_time_calls_send_with_expected_args(notifier):
    notifier.send = AsyncMock()
    await notifier.notify_low_time('child1', 'TikTok', 12)
    notifier.send.assert_awaited_once_with(
        'child1',
        title='⏰ TikTok: 12 min left',
        message='TikTok will lock soon — 12 minutes remaining today.',
        priority='high',
        tags=['hourglass'],
    )


def test_init_notifier_sets_singleton():
    """init_notifier should create and return the singleton."""
    from familylink_server.services import ntfy_notifier as mod

    mod._notifier = None
    notifier = mod.init_notifier({'child1': 'topic1'}, base_url=TEST_BASE_URL)
    assert mod.get_notifier() is notifier
    assert notifier._topics == {'child1': 'topic1'}
    assert notifier._base_url == TEST_BASE_URL
    mod._notifier = None  # cleanup
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_ntfy_notifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'familylink_server.services.ntfy_notifier'`

- [ ] **Step 3: Implement**

Create `src/familylink_server/services/ntfy_notifier.py`:

```python
"""Outbound ntfy push notification service."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class NtfyNotifier:
    """Sends push notifications to per-kid topics on a (self-hosted) ntfy server.

    Uses ntfy's JSON publish API (a single POST to `base_url` with the topic
    in the body) rather than the per-topic-URL header API — the header API
    can't safely carry UTF-8 (emoji titles) since HTTP headers are
    effectively ASCII/latin-1.
    """

    def __init__(self, topics: dict[str, str], base_url: str) -> None:
        self._topics = topics
        self._base_url = base_url

    async def send(
        self,
        child_id: str,
        title: str,
        message: str,
        priority: str = 'default',
        tags: list[str] | None = None,
    ) -> None:
        """POST a notification for `child_id`. No-op if that kid has no topic mapped."""
        topic = self._topics.get(child_id)
        if not topic:
            return
        payload: dict[str, object] = {
            'topic': topic,
            'title': title,
            'message': message,
            'priority': priority,
        }
        if tags:
            payload['tags'] = tags
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self._base_url, json=payload, timeout=10)
                resp.raise_for_status()
        except Exception:
            logger.warning('ntfy push failed for child %s', child_id, exc_info=True)

    async def notify_homework(self, child_id: str, subject: str, deadline: str) -> None:
        """Push a new-homework alert."""
        await self.send(
            child_id,
            title=f'📚 New homework — {subject}',
            message=f'Due {deadline}',
            tags=['book'],
        )

    async def notify_low_time(
        self, child_id: str, target_name: str, remaining_mins: int
    ) -> None:
        """Push a low-remaining-time warning."""
        await self.send(
            child_id,
            title=f'⏰ {target_name}: {remaining_mins} min left',
            message=(
                f'{target_name} will lock soon — '
                f'{remaining_mins} minutes remaining today.'
            ),
            priority='high',
            tags=['hourglass'],
        )


_notifier: NtfyNotifier | None = None


def init_notifier(topics: dict[str, str], base_url: str) -> NtfyNotifier:
    """Create and store the singleton. Called once in lifespan."""
    global _notifier
    _notifier = NtfyNotifier(topics, base_url)
    return _notifier


def get_notifier() -> NtfyNotifier | None:
    """Return the singleton, or None when no topics are configured."""
    return _notifier
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_ntfy_notifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/services/ntfy_notifier.py tests/server/test_ntfy_notifier.py
git commit -m "feat: add NtfyNotifier service for ntfy push notifications

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: DB columns for once-per-day low-time alerts

**Files:**
- Modify: `src/familylink_server/db/models.py`
- Create: `alembic/versions/008_low_time_alerts.py`
- Test: `tests/server/test_db_models.py`

**Interfaces:**
- Produces: `AppConfig.low_time_alerted_date: date | None`, `LinuxUsageSnapshot.low_time_alerted: bool` (default `False`). Consumed by Task 4 and Task 5.

- [ ] **Step 1: Write the failing test**

Check the existing style in `tests/server/test_db_models.py` first (read the file), then append tests matching its pattern — an in-memory-SQLite round trip for each new column:

```python
async def test_app_config_low_time_alerted_date_defaults_none(db_session):
    from familylink_server.db.models import AppConfig

    config = AppConfig(
        child_id='child1',
        app_name='TikTok',
        package_name='com.tiktok',
    )
    db_session.add(config)
    await db_session.commit()
    assert config.low_time_alerted_date is None


async def test_linux_usage_snapshot_low_time_alerted_defaults_false(db_session):
    from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot

    machine = LinuxMachine(
        child_id='child1',
        friendly_name='Test PC',
        hostname='host',
        ssh_user='user',
        ssh_private_key='key',
    )
    db_session.add(machine)
    await db_session.flush()
    snapshot = LinuxUsageSnapshot(
        machine_id=machine.id,
        date=__import__('datetime').date.today(),
    )
    db_session.add(snapshot)
    await db_session.commit()
    assert snapshot.low_time_alerted is False
```

(If `tests/server/test_db_models.py` already has a `db_session` fixture matching `tests/server/test_db_homework.py`'s in-memory-SQLite pattern, reuse it — don't redefine. If not, copy that fixture in verbatim.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_db_models.py -k low_time -v`
Expected: FAIL with `TypeError: 'low_time_alerted_date' is an invalid keyword argument` or `AttributeError`

- [ ] **Step 3: Implement — update models**

In `src/familylink_server/db/models.py`, add to `AppConfig` (after `bonus_date`):

```python
    low_time_alerted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
```

Add to `LinuxUsageSnapshot` (after `poweroff_at`, before `updated_at`):

```python
    low_time_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
```

And in `LinuxUsageSnapshot.__init__`, add the matching default:

```python
        kwargs.setdefault('low_time_alerted', False)
```

- [ ] **Step 4: Write the Alembic migration**

Create `alembic/versions/008_low_time_alerts.py`:

```python
"""add low-time-alert tracking columns to app_configs and linux_usage_snapshots

Revision ID: 008
Revises: 007
Create Date: 2026-09-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '008'
down_revision: str | Sequence[str] | None = '007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable low-time-alert tracking columns."""
    op.add_column(
        'app_configs', sa.Column('low_time_alerted_date', sa.Date(), nullable=True)
    )
    op.add_column(
        'linux_usage_snapshots',
        sa.Column(
            'low_time_alerted',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Drop low-time-alert tracking columns."""
    op.drop_column('linux_usage_snapshots', 'low_time_alerted')
    op.drop_column('app_configs', 'low_time_alerted_date')
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_db_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/db/models.py alembic/versions/008_low_time_alerts.py tests/server/test_db_models.py
git commit -m "feat: add low-time-alert tracking columns

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Low-time warning in `app_enforcer.py`

**Files:**
- Modify: `src/familylink_server/services/app_enforcer.py`
- Test: `tests/server/test_app_enforcer.py`

**Interfaces:**
- Consumes: `NtfyNotifier.notify_low_time(child_id, target_name, remaining_mins)` from Task 2; `AppConfig.low_time_alerted_date` from Task 3.
- Produces: `enforce_child(child_id, svc, notifier=None, ntfy=None)`, `app_enforcer_loop(svc, notifier=None, ntfy=None)` — both gain a new keyword-only-by-convention `ntfy` parameter alongside the existing `notifier`.

- [ ] **Step 1: Update the `_make_config` test helper**

In `tests/server/test_app_enforcer.py`, extend `_make_config` to carry the two new fields:

```python
def _make_config(
    package_name='com.example.app',
    app_name='Example App',
    auto_blocked_at=None,
    bonus_mins=0,
    bonus_date=None,
    max_mins=None,
    low_time_alerted_date=None,
):
    cfg = MagicMock()
    cfg.package_name = package_name
    cfg.app_name = app_name
    cfg.auto_blocked_at = auto_blocked_at
    cfg.bonus_mins = bonus_mins
    cfg.bonus_date = bonus_date
    cfg.max_mins = max_mins
    cfg.low_time_alerted_date = low_time_alerted_date
    return cfg
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/server/test_app_enforcer.py`:

```python
async def test_enforce_child_sends_low_time_warning_under_threshold():
    """Remaining time crosses under 15 min -> ntfy.notify_low_time fires once, date stamped."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config(app_name='TikTok')
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=20 * 60)],  # 10 min remaining
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()
    mock_ntfy = MagicMock()
    mock_ntfy.notify_low_time = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc, ntfy=mock_ntfy)

    mock_ntfy.notify_low_time.assert_awaited_once_with('child1', 'TikTok', 10)
    assert config.low_time_alerted_date == datetime.date.today()


async def test_enforce_child_does_not_resend_low_time_warning_same_day():
    """Already alerted today -> notify_low_time is not called again."""
    from familylink_server.services.app_enforcer import enforce_child

    today = datetime.date.today()
    config = _make_config(low_time_alerted_date=today)
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=20 * 60)],  # still 10 min remaining
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()
    mock_ntfy = MagicMock()
    mock_ntfy.notify_low_time = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc, ntfy=mock_ntfy)

    mock_ntfy.notify_low_time.assert_not_awaited()


async def test_enforce_child_skips_low_time_warning_when_well_over_threshold():
    """Remaining time is above the threshold -> no warning."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config()
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=5 * 60)],  # 25 min remaining
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()
    mock_ntfy = MagicMock()
    mock_ntfy.notify_low_time = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc, ntfy=mock_ntfy)

    mock_ntfy.notify_low_time.assert_not_awaited()


async def test_enforce_child_skips_low_time_warning_when_already_blocked():
    """App already blocked today -> no low-time warning (it's already blocked, not 'soon')."""
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
    mock_ntfy = MagicMock()
    mock_ntfy.notify_low_time = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc, ntfy=mock_ntfy)

    mock_ntfy.notify_low_time.assert_not_awaited()


async def test_enforce_child_low_time_warning_noop_without_ntfy():
    """No ntfy notifier passed -> no error, nothing sent."""
    from familylink_server.services.app_enforcer import enforce_child

    config = _make_config()
    usage = _make_usage(
        [_make_app(limit_mins=30)],
        [_make_usage_session(usage_seconds=20 * 60)],
    )
    mock_ctx, _ = _make_session_ctx([config])
    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.block_app = AsyncMock()

    with patch(
        'familylink_server.services.app_enforcer.make_session', return_value=mock_ctx
    ):
        await enforce_child('child1', mock_svc)  # no ntfy kwarg — must not raise

    assert config.low_time_alerted_date == datetime.date.today()
```

- [ ] **Step 3: Update the two existing loop tests for the new `ntfy` kwarg**

In `test_app_enforcer_loop_calls_enforce_child_for_each_distinct_child`, change:

```python
    mock_enforce.assert_any_await('child1', mock_svc, notifier=None)
    mock_enforce.assert_any_await('child2', mock_svc, notifier=None)
```

to:

```python
    mock_enforce.assert_any_await('child1', mock_svc, notifier=None, ntfy=None)
    mock_enforce.assert_any_await('child2', mock_svc, notifier=None, ntfy=None)
```

In `test_app_enforcer_loop_logs_and_continues_when_one_child_raises`, change the side-effect signature:

```python
    async def _enforce_side_effect(child_id, svc, notifier=None):
```

to:

```python
    async def _enforce_side_effect(child_id, svc, notifier=None, ntfy=None):
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_app_enforcer.py -v`
Expected: FAIL — new tests error with `TypeError: enforce_child() got an unexpected keyword argument 'ntfy'`; the two updated loop tests fail on the assertion/signature mismatch.

- [ ] **Step 5: Implement**

In `src/familylink_server/services/app_enforcer.py`:

Add the threshold constant near `POLL_INTERVAL`:

```python
LOW_TIME_THRESHOLD_MINS = 15
```

Update the `TYPE_CHECKING` import block to add the ntfy type:

```python
if TYPE_CHECKING:
    from familylink.models import AppUsage
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService
    from familylink_server.services.ntfy_notifier import NtfyNotifier
```

Update `enforce_child`'s signature and insert the low-time check right after `usage_mins` is computed, before the over-limit `if`:

```python
async def enforce_child(
    child_id: str,
    svc: FamilyLinkService,
    notifier: DiscordNotifier | None = None,
    ntfy: NtfyNotifier | None = None,
) -> None:
    """Block/restore one child's opted-in apps based on live Google usage vs. limit."""
    today = date.today()
    async with make_session() as session:
        ...
            bonus = config.bonus_mins if config.bonus_date == today else 0
            effective_limit = limit_mins + bonus
            usage_mins = usage_by_package.get(config.package_name, 0.0)

            remaining_mins = effective_limit - usage_mins
            if (
                config.auto_blocked_at is None
                and config.low_time_alerted_date != today
                and 0 < remaining_mins <= LOW_TIME_THRESHOLD_MINS
            ):
                config.low_time_alerted_date = today
                if ntfy:
                    await ntfy.notify_low_time(
                        child_id, config.app_name, round(remaining_mins)
                    )

            if (
                usage_mins >= effective_limit
                and config.auto_blocked_at is None
                and not app.supervision_setting.hidden
            ):
                ...
```

(Only the new block is added — the surrounding code is unchanged; splice it in at the matching location rather than retyping the whole function.)

Update `app_enforcer_loop`:

```python
async def app_enforcer_loop(
    svc: FamilyLinkService,
    notifier: DiscordNotifier | None = None,
    ntfy: NtfyNotifier | None = None,
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

            results = await asyncio.gather(
                *[
                    enforce_child(child_id, svc, notifier=notifier, ntfy=ntfy)
                    for child_id in child_ids
                ],
                return_exceptions=True,
            )
            for child_id, outcome in zip(child_ids, results, strict=True):
                if isinstance(outcome, Exception):
                    logger.exception(
                        'enforce_child failed for child %s', child_id, exc_info=outcome
                    )
        except Exception:
            logger.exception('App enforcer cycle failed')
        await asyncio.sleep(POLL_INTERVAL)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_app_enforcer.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 7: Commit**

```bash
git add src/familylink_server/services/app_enforcer.py tests/server/test_app_enforcer.py
git commit -m "feat: warn via ntfy when an app's remaining time drops under 15 min

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Low-time warning in `linux_poller.py`

**Files:**
- Modify: `src/familylink_server/services/linux_poller.py`
- Test: `tests/server/test_linux_poller.py`

**Interfaces:**
- Consumes: `NtfyNotifier.notify_low_time` from Task 2; `LinuxUsageSnapshot.low_time_alerted` from Task 3.
- Produces: `poll_machine(machine, notifier=None, ntfy=None, now=None)`, `poller_loop(notifier=None, ntfy=None)`.

- [ ] **Step 1: Update the `_make_snapshot` test helper**

In `tests/server/test_linux_poller.py`, extend `_make_snapshot`:

```python
def _make_snapshot(
    active_seconds: int = 0,
    locked_at: datetime.datetime | None = None,
    poweroff_at: datetime.datetime | None = None,
    bonus_mins: int = 0,
    low_time_alerted: bool = False,
) -> MagicMock:
    snap = MagicMock()
    snap.active_seconds = active_seconds
    snap.locked_at = locked_at
    snap.poweroff_at = poweroff_at
    snap.bonus_mins = bonus_mins
    snap.low_time_alerted = low_time_alerted
    snap.updated_at = None
    return snap
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/server/test_linux_poller.py` (read the file first for the exact `check_session`/`make_session` patch style used by neighboring `poll_machine` tests — mirror it exactly):

```python
async def test_poll_machine_sends_low_time_warning_under_threshold():
    """Remaining time crosses under 15 min -> ntfy.notify_low_time fires once."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=20, friendly_name='Kid PC')
    snapshot = _make_snapshot(active_seconds=10 * 60)  # 10 min active -> 10 min remaining after this poll
    mock_ctx, _ = _make_session_ctx(snapshot)
    mock_ntfy = MagicMock()
    mock_ntfy.notify_low_time = AsyncMock()

    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, ntfy=mock_ntfy)

    # active_seconds becomes 660 (11 min) -> 9 min remaining, under the 15-min threshold
    mock_ntfy.notify_low_time.assert_awaited_once_with('child1', 'Kid PC', 9)
    assert snapshot.low_time_alerted is True


async def test_poll_machine_does_not_resend_low_time_warning():
    """Already alerted -> notify_low_time is not called again."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=20)
    snapshot = _make_snapshot(active_seconds=10 * 60, low_time_alerted=True)
    mock_ctx, _ = _make_session_ctx(snapshot)
    mock_ntfy = MagicMock()
    mock_ntfy.notify_low_time = AsyncMock()

    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, ntfy=mock_ntfy)

    mock_ntfy.notify_low_time.assert_not_awaited()


async def test_poll_machine_skips_low_time_warning_when_no_limit():
    """No daily_limit_mins configured -> no warning (nothing to run out of)."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=None)
    snapshot = _make_snapshot(active_seconds=10 * 60)
    mock_ctx, _ = _make_session_ctx(snapshot)
    mock_ntfy = MagicMock()
    mock_ntfy.notify_low_time = AsyncMock()

    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, ntfy=mock_ntfy)

    mock_ntfy.notify_low_time.assert_not_awaited()


async def test_poll_machine_low_time_warning_noop_without_ntfy():
    """No ntfy notifier passed -> no error, flag still stamped."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=20)
    snapshot = _make_snapshot(active_seconds=10 * 60)
    mock_ctx, _ = _make_session_ctx(snapshot)

    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)  # no ntfy kwarg — must not raise

    assert snapshot.low_time_alerted is True
```

Note: `_make_machine` already sets `m.child_id` implicitly to a `MagicMock` unless given — check the helper; if it doesn't set `child_id` explicitly, add `child_id: str = 'child1'` to `_make_machine`'s params and `m.child_id = child_id` in its body before using these tests (match whatever the existing helper does for other fields you don't see in the excerpt already read).

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_linux_poller.py -v`
Expected: FAIL with `TypeError: poll_machine() got an unexpected keyword argument 'ntfy'`

- [ ] **Step 4: Implement**

In `src/familylink_server/services/linux_poller.py`:

Add the threshold constant near `POLL_INTERVAL`:

```python
LOW_TIME_THRESHOLD_SECS = 15 * 60
```

Update the `TYPE_CHECKING` import:

```python
if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.ntfy_notifier import NtfyNotifier
```

Update `poll_machine`'s signature and insert the check right after `effective_limit_secs`/`effective_window_start`/`in_window` are computed, before the lock-application `if`:

```python
async def poll_machine(
    machine: LinuxMachine,
    notifier: DiscordNotifier | None = None,
    ntfy: NtfyNotifier | None = None,
    now: datetime | None = None,
) -> None:
    """Poll one machine: skip if powered off, accumulate active seconds, enforce limits.

    Args:
        machine: The LinuxMachine ORM instance to poll.
        notifier: Optional Discord notifier; posts on lock/poweroff when provided.
        ntfy: Optional ntfy notifier; posts a low-time warning when provided.
        now: Current time, injectable for tests; defaults to datetime.now(UTC).
    """
    ...
        effective_window_start = (
            _shift_time_later(machine.window_start_time, snapshot.bonus_mins)
            if machine.window_start_time is not None
            else None
        )
        in_window = _in_window(
            now.astimezone(LOCAL_TZ).time(),
            effective_window_start,
            machine.window_end_time,
        )

        if (
            effective_limit_secs is not None
            and not snapshot.low_time_alerted
            and snapshot.locked_at is None
        ):
            remaining_secs = effective_limit_secs - snapshot.active_seconds
            if 0 < remaining_secs <= LOW_TIME_THRESHOLD_SECS:
                snapshot.low_time_alerted = True
                if ntfy:
                    await ntfy.notify_low_time(
                        machine.child_id, machine.friendly_name, remaining_secs // 60
                    )

        if (
            (
                effective_limit_secs is not None
                and snapshot.active_seconds >= effective_limit_secs
            )
            or in_window
        ) and snapshot.poweroff_at is None:
            ...
```

(Only the new block between `in_window = ...` and the existing `if ( ( effective_limit_secs ...` lock-check is added — everything else in the function is unchanged.)

Update `poller_loop`:

```python
async def poller_loop(
    notifier: DiscordNotifier | None = None, ntfy: NtfyNotifier | None = None
) -> None:
    """Main poll loop — iterates all enabled machines every POLL_INTERVAL seconds.

    Args:
        notifier: Optional Discord notifier passed down to each poll_machine call.
        ntfy: Optional ntfy notifier passed down to each poll_machine call.
    """
    while True:
        try:
            async with make_session() as session:
                result = await session.execute(
                    select(LinuxMachine).where(LinuxMachine.enabled.is_(True))
                )
                machines = result.scalars().all()

            await asyncio.gather(
                *[poll_machine(m, notifier=notifier, ntfy=ntfy) for m in machines],
                return_exceptions=True,
            )
        except Exception:
            logger.exception('Poller cycle failed')
        await asyncio.sleep(POLL_INTERVAL)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_linux_poller.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/services/linux_poller.py tests/server/test_linux_poller.py
git commit -m "feat: warn via ntfy when a Linux machine's remaining time drops under 15 min

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Notify on new homework

**Files:**
- Modify: `src/familylink_server/db/homework.py`
- Modify: `src/familylink_server/routers/homework.py`
- Test: `tests/server/test_db_homework.py`
- Test: `tests/server/test_routers_homework.py`

**Interfaces:**
- Consumes: `NtfyNotifier.notify_homework` and `get_notifier()` from Task 2.
- Produces: `upsert_homework_entries(...) -> list[dict[str, str | date]]` — now returns the subset of `entries` that were newly created (not refreshed). Existing callers that ignored the return value are unaffected.

- [ ] **Step 1: Write the failing DB-layer test**

Append to `tests/server/test_db_homework.py`:

```python
@pytest.mark.asyncio
async def test_upsert_returns_only_newly_created_entries(db_session):
    """First call: both entries are new. Second call, one repeated + one new:
    only the genuinely new one comes back.
    """
    new_entries = await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'a'},
            {'subject': 'Angol', 'deadline': date(2026, 9, 10), 'description': 'b'},
        ],
    )
    await db_session.commit()
    assert sorted(e['subject'] for e in new_entries) == ['Angol', 'Matek']

    more_entries = await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 9),
        [
            {'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'refreshed'},
            {'subject': 'Torna', 'deadline': date(2026, 9, 11), 'description': 'c'},
        ],
    )
    await db_session.commit()
    assert [e['subject'] for e in more_entries] == ['Torna']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_db_homework.py -k returns_only_newly_created -v`
Expected: FAIL with `assert sorted(e['subject'] for e in None) == [...]` (or `TypeError: 'NoneType' object is not iterable`)

- [ ] **Step 3: Implement the DB-layer change**

In `src/familylink_server/db/homework.py`, change `upsert_homework_entries`:

```python
async def upsert_homework_entries(
    session: AsyncSession,
    child_id: str,
    today: date,
    entries: list[dict[str, str | date]],
) -> list[dict[str, str | date]]:
    """Insert-or-refresh a kid's homework, keyed by (child_id, subject, deadline).

    Each entry is `{'subject': str, 'deadline': date, 'description': str}`. A
    still-open item scraped again refreshes its description/date/fetched_at
    in place rather than duplicating.

    Returns the subset of `entries` that were newly created this call (not
    refreshed) — callers use this to notify only on genuinely new homework.
    """
    fetched_at = datetime.now(UTC)
    new_entries: list[dict[str, str | date]] = []
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
            new_entries.append(entry)
    return new_entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/server/test_db_homework.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Fix the existing router test's mock and write the failing router test**

In `tests/server/test_routers_homework.py`, `test_ingest_upserts_and_prunes` currently does `upsert_mock = AsyncMock()` with no return value — once the router iterates the return value, an unconfigured `AsyncMock`'s return is a non-iterable `MagicMock`, which would break this test. Fix it:

```python
    upsert_mock = AsyncMock(return_value=[])
```

(Change only that line; the rest of the test is unchanged.)

Then append new tests:

```python
@freeze_time('2026-09-08')
def test_ingest_notifies_ntfy_for_new_homework_only(monkeypatch):
    """Only entries upsert_homework_entries reports as new trigger a push."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    import familylink_server.routers.homework as homework_router

    monkeypatch.setattr(
        homework_router,
        'upsert_homework_entries',
        AsyncMock(
            return_value=[
                {
                    'subject': 'Matek',
                    'deadline': date(2026, 9, 10),
                    'description': 'x',
                }
            ]
        ),
    )
    monkeypatch.setattr(homework_router, 'prune_expired_homework', AsyncMock())
    mock_ntfy = AsyncMock()
    monkeypatch.setattr(homework_router, 'get_notifier', lambda: mock_ntfy)

    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={
                'child_id': 'child1',
                'entries': [
                    {
                        'subject': 'Matek',
                        'teacher': '',
                        'deadline': '2026-09-10',
                        'text': '',
                        'attachments': [],
                    }
                ],
            },
            headers={'X-Api-Key': 'secret'},
        )
    finally:
        _pop_session_override()

    assert resp.status_code == 204
    mock_ntfy.notify_homework.assert_awaited_once_with('child1', 'Matek', '2026-09-10')


@freeze_time('2026-09-08')
def test_ingest_skips_ntfy_when_no_new_entries(monkeypatch):
    """upsert_homework_entries reports no new entries -> notify_homework is never called."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    import familylink_server.routers.homework as homework_router

    monkeypatch.setattr(
        homework_router, 'upsert_homework_entries', AsyncMock(return_value=[])
    )
    monkeypatch.setattr(homework_router, 'prune_expired_homework', AsyncMock())
    mock_ntfy = AsyncMock()
    monkeypatch.setattr(homework_router, 'get_notifier', lambda: mock_ntfy)

    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={'child_id': 'child1', 'entries': []},
            headers={'X-Api-Key': 'secret'},
        )
    finally:
        _pop_session_override()

    assert resp.status_code == 204
    mock_ntfy.notify_homework.assert_not_awaited()


@freeze_time('2026-09-08')
def test_ingest_skips_ntfy_when_disabled(monkeypatch):
    """get_notifier() returns None (ntfy not configured) -> no error."""
    monkeypatch.setattr(settings, 'ekreta_ingest_token', 'secret')
    import familylink_server.routers.homework as homework_router

    monkeypatch.setattr(
        homework_router,
        'upsert_homework_entries',
        AsyncMock(
            return_value=[
                {'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'x'}
            ]
        ),
    )
    monkeypatch.setattr(homework_router, 'prune_expired_homework', AsyncMock())
    monkeypatch.setattr(homework_router, 'get_notifier', lambda: None)

    client = _client()
    try:
        resp = client.post(
            '/internal/ekreta/homework',
            json={'child_id': 'child1', 'entries': []},
            headers={'X-Api-Key': 'secret'},
        )
    finally:
        _pop_session_override()

    assert resp.status_code == 204
```

- [ ] **Step 6: Run tests to verify they fail (for the two new tests)**

Run: `python -m pytest tests/server/test_routers_homework.py -v`
Expected: `test_ingest_notifies_ntfy_for_new_homework_only` and `test_ingest_skips_ntfy_when_no_new_entries` FAIL (`AttributeError: module ... has no attribute 'get_notifier'`); `test_ingest_upserts_and_prunes` now PASSes again after the mock fix.

- [ ] **Step 7: Implement the router change**

In `src/familylink_server/routers/homework.py`, add the import:

```python
from familylink_server.services.ntfy_notifier import get_notifier
```

Update `ingest_homework`:

```python
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
    new_entries = await upsert_homework_entries(session, body.child_id, today, entries)
    await prune_expired_homework(session, body.child_id, today)
    await session.commit()

    ntfy = get_notifier()
    if ntfy:
        for entry in new_entries:
            await ntfy.notify_homework(
                body.child_id, entry['subject'], entry['deadline'].isoformat()
            )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_routers_homework.py tests/server/test_db_homework.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Commit**

```bash
git add src/familylink_server/db/homework.py src/familylink_server/routers/homework.py tests/server/test_db_homework.py tests/server/test_routers_homework.py
git commit -m "feat: push ntfy notification for genuinely new homework only

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Wire the singleton into `main.py`

**Files:**
- Modify: `src/familylink_server/main.py`
- Test: `tests/server/test_main.py`

**Interfaces:**
- Consumes: `ntfy_notifier.init_notifier`/`get_notifier` from Task 2, `settings.ntfy_topics_parsed` from Task 1, `app_enforcer_loop(..., ntfy=...)` from Task 4, `poller_loop(..., ntfy=...)` from Task 5.

- [ ] **Step 1: Write the failing test**

Append to `tests/server/test_main.py`:

```python
async def test_ntfy_initialized_when_topics_configured():
    """Lifespan should init the ntfy singleton and pass it into both loops."""
    from familylink_server.main import app, lifespan

    async def _fake_poller(*args, **kwargs):
        """Coroutine that exits immediately (stands in for poller_loop)."""

    async def _fake_enforcer(*args, **kwargs):
        """Coroutine that exits immediately (stands in for app_enforcer_loop)."""

    async def _fake_health_check(*args, **kwargs):
        """Coroutine that exits immediately (stands in for health_check_loop)."""

    async def _fake_proactive_refresh(*args, **kwargs):
        """Coroutine that exits immediately (stands in for proactive_refresh_loop)."""

    with (
        patch('familylink_server.main.init_service'),
        patch('familylink_server.main.get_service'),
        patch('familylink_server.main.settings') as mock_settings,
        patch('familylink_server.main.poller_loop', side_effect=_fake_poller),
        patch('familylink_server.main.app_enforcer_loop', side_effect=_fake_enforcer),
        patch(
            'familylink_server.main.health_check_loop', side_effect=_fake_health_check
        ),
        patch(
            'familylink_server.main.proactive_refresh_loop',
            side_effect=_fake_proactive_refresh,
        ),
    ):
        mock_settings.discord_enabled = False
        mock_settings.ntfy_topics_parsed = {'child1': 'topic1'}
        mock_settings.ntfy_base_url = 'http://ntfy.test'
        async with lifespan(app):
            from familylink_server.services.ntfy_notifier import get_notifier

            notifier = get_notifier()
            assert notifier is not None
            assert notifier._topics == {'child1': 'topic1'}
            assert notifier._base_url == 'http://ntfy.test'


async def test_ntfy_not_initialized_when_no_topics_configured():
    """No topics configured -> singleton stays unset."""
    from familylink_server.main import app, lifespan
    from familylink_server.services import ntfy_notifier as ntfy_mod

    ntfy_mod._notifier = None

    async def _fake_loop(*args, **kwargs):
        """Coroutine that exits immediately."""

    with (
        patch('familylink_server.main.init_service'),
        patch('familylink_server.main.get_service'),
        patch('familylink_server.main.settings') as mock_settings,
        patch('familylink_server.main.poller_loop', side_effect=_fake_loop),
        patch('familylink_server.main.app_enforcer_loop', side_effect=_fake_loop),
        patch('familylink_server.main.health_check_loop', side_effect=_fake_loop),
        patch('familylink_server.main.proactive_refresh_loop', side_effect=_fake_loop),
    ):
        mock_settings.discord_enabled = False
        mock_settings.ntfy_topics_parsed = {}
        async with lifespan(app):
            pass

    assert ntfy_mod.get_notifier() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_main.py -k ntfy -v`
Expected: FAIL — `test_ntfy_initialized_when_topics_configured` asserts `notifier is not None` but gets `None`.

- [ ] **Step 3: Implement**

In `src/familylink_server/main.py`, add the import next to the other loop imports:

```python
from familylink_server.services.linux_poller import poller_loop
from familylink_server.services.ntfy_notifier import init_notifier as init_ntfy_notifier
```

In `lifespan`, after the existing Discord `if/else` block and before `poller_task = ...`, add:

```python
    ntfy = None
    topics = settings.ntfy_topics_parsed
    if topics:
        ntfy = init_ntfy_notifier(topics, base_url=settings.ntfy_base_url)
        logger.info(
            'ntfy notifications enabled for %d kid(s) via %s',
            len(topics),
            settings.ntfy_base_url,
        )
    else:
        logger.info('ntfy notifications disabled (NTFY_TOPICS not set)')

    poller_task = asyncio.create_task(poller_loop(notifier=notifier, ntfy=ntfy))
    logger.info('Linux machine poller started')

    enforcer_task = asyncio.create_task(
        app_enforcer_loop(get_service(), notifier=notifier, ntfy=ntfy)
    )
    logger.info('App overuse enforcer started')
```

(This replaces the existing two lines that create `poller_task` and `enforcer_task` — everything else in `lifespan` is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/server/test_main.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Run the full server test suite**

Run: `python -m pytest tests/server/ -v`
Expected: PASS — this is the integration checkpoint for the whole feature.

- [ ] **Step 6: Update README/env docs**

Check `README.md` for an environment-variables table (it documents `DISCORD_BOT_TOKEN` etc. per the project's existing convention) and add rows for `NTFY_TOPICS` and `NTFY_BASE_URL`, e.g.:

```
| `NTFY_TOPICS` | No | `` | Per-kid ntfy push topics: `child_id:topic,child_id:topic`. Empty disables ntfy notifications. |
| `NTFY_BASE_URL` | No | `http://ntfy-qs0o4os08kggkcgs4kos4sgk.192.168.0.22.sslip.io` | Base URL of the ntfy server (self-hosted intranet instance by default). |
```

Match whatever column format the existing table uses exactly — read it first.

- [ ] **Step 7: Commit**

```bash
git add src/familylink_server/main.py tests/server/test_main.py README.md
git commit -m "feat: wire ntfy notifier into app enforcer and Linux poller

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Playwright smoke-test for every kid's ntfy topic

**Files:**
- Create: `scripts/verify_ntfy_topics.py`
- Modify: `README.md` (short "Verifying ntfy setup" note)

**Interfaces:**
- Consumes: `settings.ntfy_topics_parsed`, `settings.ntfy_base_url` (Task 1), `NtfyNotifier` (Task 2).
- Produces: nothing consumed by other tasks — a standalone ops script, not part of the pytest suite. It hits the real self-hosted ntfy instance directly, so it can't be a unit test.

Confirmed for this server: **open access** (no accounts/ACLs — a topic's only protection is an unguessable name). So there's nothing to *provision* server-side; "configure for every kid" here means confirming each kid's topic (from `NTFY_TOPICS`, keyed by the same `child_id` values already used elsewhere in this app) actually delivers, end to end, through the real web UI a kid would see.

- [ ] **Step 1: Install Playwright locally (not a project dependency)**

This is a one-off verification tool against a real external server, not app code — don't add it to `pyproject.toml`. Install it ad hoc:

```bash
pip install playwright
playwright install chromium
```

- [ ] **Step 2: Write the script**

Create `scripts/verify_ntfy_topics.py`:

```python
#!/usr/bin/env python
"""One-off Playwright smoke test: confirms every configured kid's ntfy topic
is reachable and renders a live push in the ntfy web UI.

Not part of the pytest suite — this hits the real, self-hosted ntfy server
configured via NTFY_BASE_URL/NTFY_TOPICS. Run manually after configuring
those env vars (see README "Verifying ntfy setup"):

    pip install playwright && playwright install chromium
    python scripts/verify_ntfy_topics.py
"""

from __future__ import annotations

import asyncio
import sys

from playwright.async_api import Browser, async_playwright

from familylink_server.config import settings
from familylink_server.services.ntfy_notifier import NtfyNotifier


async def _check_one(
    browser: Browser, notifier: NtfyNotifier, child_id: str, topic: str
) -> bool:
    """Open the topic's live web view, push a test message, confirm it renders."""
    page = await browser.new_page()
    marker = f'verify-{child_id}'
    try:
        await page.goto(f'{settings.ntfy_base_url}/{topic}', wait_until='networkidle')
        await notifier.send(child_id, 'Verify', marker)
        await page.get_by_text(marker).wait_for(timeout=15_000)
        await page.screenshot(path=f'/tmp/ntfy-verify-{child_id}.png')
        print(f'OK   {child_id:12s} topic={topic}')
        return True
    except Exception as exc:
        print(f'FAIL {child_id:12s} topic={topic}  ({exc})')
        return False
    finally:
        await page.close()


async def main() -> int:
    topics = settings.ntfy_topics_parsed
    if not topics:
        print('NTFY_TOPICS is empty — nothing to verify.')
        return 1

    notifier = NtfyNotifier(topics, base_url=settings.ntfy_base_url)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            results = await asyncio.gather(
                *[
                    _check_one(browser, notifier, child_id, topic)
                    for child_id, topic in topics.items()
                ]
            )
        finally:
            await browser.close()

    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 3: Run it against the real server**

Run: `NTFY_TOPICS='child1:familylink-child1-abc123,child2:familylink-child2-def456' python scripts/verify_ntfy_topics.py` (substitute real child_ids/topics; other required `Settings` fields — `DATABASE_URL`, `SECRET_KEY`, etc. — must already be set, e.g. via the project's `.env`).
Expected: `OK   <child_id>   topic=<topic>` for every kid, exit code 0. A `FAIL` line means that kid's topic didn't render a push within 15s — check `NTFY_BASE_URL` is reachable from this machine and the topic string matches what's on the kid's phone.

**Environment note for the implementer:** this sandbox has no route to `192.168.0.22` (the intranet ntfy host), so a real live run here will time out on DNS/connect, not on the assertion logic. Write and unit-exercise the script normally; for Step 3 treat "the script runs, prints `FAIL ... (connection error)` for a deliberately-unreachable-from-here host, and exits 1" as sufficient local verification, and report DONE_WITH_CONCERNS noting that a true live check needs to run from a machine on that intranet.

- [ ] **Step 4: Document it in the README**

Add a short section to `README.md` (near wherever Discord/eKRÉTA setup is documented — match that section's format) explaining: set `NTFY_TOPICS`/`NTFY_BASE_URL`, install the ntfy app on each kid's phone subscribed to their topic, then run `scripts/verify_ntfy_topics.py` to confirm delivery end to end.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_ntfy_topics.py README.md
git commit -m "chore: add Playwright smoke test for per-kid ntfy topics

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run the entire suite: `python -m pytest`
- [ ] Run lint: `ruff check src tests`
- [ ] Run type check: `mypy src`
- [ ] Run `alembic upgrade head` against a scratch DB to confirm migration 008 applies cleanly on top of 007.
- [ ] `python scripts/verify_ntfy_topics.py` against the real intranet ntfy server, once `NTFY_TOPICS` is set for every kid (from a machine that can actually reach it — see Task 8's environment note).
- [ ] `graphify update .` to refresh the knowledge graph with the new files (per this repo's CLAUDE.md).
