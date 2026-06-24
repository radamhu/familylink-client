# Discord Bot Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Discord bot that runs inside the existing FastAPI container, provides full slash-command parity with the web UI, posts real-time change alerts with action buttons, and sends a scheduled daily usage summary.

**Architecture:** The bot runs as an `asyncio.create_task()` in FastAPI's lifespan, sharing the existing `FamilyLinkService` singleton. A new `DiscordNotifier` service is the outbound bridge called by both the bot commands and the existing web routers after every write. Commands are guild-scoped for instant sync.

**Tech Stack:** `discord.py>=2.4`, `app_commands` (slash commands), `discord.ext.tasks` (scheduled summary), `discord.ui.View` (action buttons), `pytest` + `unittest.mock` for tests.

## Global Constraints

- Python 3.12 (`.python-version` pins this); use `python -m pytest` not `uv run pytest`
- `discord.py>=2.4` added to the `server` extras in `pyproject.toml`
- All Discord settings are optional; if `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, or `DISCORD_CHANNEL_ID` is absent the bot task is silently skipped and the web server starts normally
- `DISCORD_ALLOWED_ROLE` defaults to `"Parent"`; `DISCORD_SUMMARY_TIME` defaults to `"20:00"` (HH:MM UTC)
- All slash commands are guild-scoped (sync via `bot.tree.sync(guild=discord.Object(id=guild_id))`)
- Authorization: every command and button checks the invoking user has the configured role; failures return an ephemeral error message
- `child` parameter: if omitted and exactly one supervised child exists, use that child automatically; if multiple children exist return an ephemeral error
- Action button views have `timeout=300` (5 minutes)
- Ruff style: single-quoted inline strings, Google docstring convention

---

## File Map

**New files:**
- `src/familylink_server/bot/__init__.py` — empty package marker
- `src/familylink_server/bot/client.py` — `FamilyLinkBot(commands.Bot)`: `setup_hook`, `on_ready`, restart wrapper, daily summary task
- `src/familylink_server/bot/commands/__init__.py` — `require_discord_role`, `child_autocomplete`, `resolve_child`
- `src/familylink_server/bot/commands/apps.py` — `AppsGroup(app_commands.Group)`: list, limit, block, allow
- `src/familylink_server/bot/commands/devices.py` — `DevicesGroup(app_commands.Group)`: list, lock, unlock
- `src/familylink_server/bot/commands/usage.py` — standalone commands: `/usage today`, `/usage history`, `/status`, `/refresh`
- `src/familylink_server/bot/embeds.py` — pure embed builder functions
- `src/familylink_server/bot/views.py` — `discord.ui.View` subclasses for action buttons
- `src/familylink_server/services/discord_notifier.py` — `DiscordNotifier` outbound notification service + module singleton
- `tests/server/test_discord_notifier.py`
- `tests/server/test_bot_embeds.py`
- `tests/server/test_bot_commands.py`
- `tests/server/test_bot_views.py`
- `tests/server/test_routers_discord.py`

**Modified files:**
- `pyproject.toml` — add `discord.py>=2.4` to `server` extras
- `src/familylink_server/config.py` — add Discord settings fields + `discord_enabled` property
- `src/familylink_server/main.py` — start bot task in lifespan
- `src/familylink_server/routers/apps.py` — call `notify_change` after each write
- `src/familylink_server/routers/devices.py` — call `notify_change` after each write
- `.env.example` — document new Discord env vars

---

## Task 1: Configuration + Dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/familylink_server/config.py`
- Modify: `.env.example`
- Test: `tests/server/test_config.py` (already exists — add Discord assertions)

**Interfaces:**
- Produces: `settings.discord_enabled: bool`, `settings.discord_bot_token: str | None`, `settings.discord_guild_id: int | None`, `settings.discord_channel_id: int | None`, `settings.discord_allowed_role: str`, `settings.discord_summary_time_parsed: datetime.time`

- [ ] **Step 1: Add `discord.py` to server extras in `pyproject.toml`**

In `pyproject.toml`, find the `[project.optional-dependencies]` `server` list and append `"discord.py>=2.4"`:

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
]
```

- [ ] **Step 2: Install the new dependency**

```bash
pip install -e ".[dev,test,server]"
```

Expected: resolves and installs `discord.py 2.4.x`.

- [ ] **Step 3: Add Discord settings to `config.py`**

Replace the contents of `src/familylink_server/config.py` with:

```python
"""Application settings loaded from environment variables."""

import datetime

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = ConfigDict(
        env_file='.env', env_file_encoding='utf-8', extra='ignore'
    )

    database_url: str
    secret_key: str
    google_client_id: str
    google_client_secret: str
    familylink_google_email: str
    familylink_cookies_b64: str = ''
    familylink_cookie_file: str = ''
    familylink_sapisid: str = ''
    cache_ttl_seconds: int = 900
    debug: bool = False

    discord_bot_token: str | None = None
    discord_guild_id: int | None = None
    discord_channel_id: int | None = None
    discord_allowed_role: str = 'Parent'
    discord_summary_time: str = '20:00'

    @property
    def discord_enabled(self) -> bool:
        """True when all three required Discord vars are set."""
        return bool(
            self.discord_bot_token
            and self.discord_guild_id
            and self.discord_channel_id
        )

    @property
    def discord_summary_time_parsed(self) -> datetime.time:
        """Parse HH:MM string into a UTC datetime.time."""
        h, m = self.discord_summary_time.split(':')
        return datetime.time(int(h), int(m), tzinfo=datetime.timezone.utc)


settings = Settings()
```

- [ ] **Step 4: Document new vars in `.env.example`**

Append the following block to `.env.example` (after the existing content):

```
# ------------------------------------------
# Discord bot (optional — all three required to enable)
# ------------------------------------------

# Bot token from Discord Developer Portal → Bot → Token
# DISCORD_BOT_TOKEN=

# Discord server (guild) ID (enable Developer Mode → right-click server → Copy ID)
# DISCORD_GUILD_ID=

# Channel ID for outbound notifications (right-click channel → Copy ID)
# DISCORD_CHANNEL_ID=

# Name of the Discord role allowed to run bot commands (default: Parent)
# DISCORD_ALLOWED_ROLE=Parent

# Daily summary time in HH:MM UTC (default: 20:00)
# DISCORD_SUMMARY_TIME=20:00
```

- [ ] **Step 5: Write failing tests for the new settings**

Add to `tests/server/test_config.py`:

```python
import datetime
import os

import pytest


def test_discord_disabled_by_default():
    from familylink_server.config import Settings
    s = Settings()
    assert s.discord_enabled is False


def test_discord_enabled_when_all_vars_set(monkeypatch):
    from familylink_server.config import Settings
    monkeypatch.setenv('DISCORD_BOT_TOKEN', 'token')
    monkeypatch.setenv('DISCORD_GUILD_ID', '123456')
    monkeypatch.setenv('DISCORD_CHANNEL_ID', '789012')
    s = Settings()
    assert s.discord_enabled is True
    assert s.discord_guild_id == 123456
    assert s.discord_channel_id == 789012


def test_discord_summary_time_parsed():
    from familylink_server.config import Settings
    s = Settings()
    t = s.discord_summary_time_parsed
    assert t == datetime.time(20, 0, tzinfo=datetime.timezone.utc)


def test_discord_summary_time_custom(monkeypatch):
    from familylink_server.config import Settings
    monkeypatch.setenv('DISCORD_SUMMARY_TIME', '08:30')
    s = Settings()
    t = s.discord_summary_time_parsed
    assert t == datetime.time(8, 30, tzinfo=datetime.timezone.utc)
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/server/test_config.py -v
```

Expected: all Discord config tests PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/familylink_server/config.py .env.example tests/server/test_config.py
git commit -m "feat: add Discord configuration settings"
```

---

## Task 2: DiscordNotifier Service

**Files:**
- Create: `src/familylink_server/services/discord_notifier.py`
- Create: `tests/server/test_discord_notifier.py`

**Interfaces:**
- Consumes: `discord.TextChannel` (set after bot ready), embed builders from Task 3 (imported lazily to avoid circular import)
- Produces:
  - `DiscordNotifier.set_channel(channel: discord.TextChannel) -> None`
  - `DiscordNotifier.notify_change(action, child_name, target, source, view=None) -> None` (async)
  - `DiscordNotifier.post_daily_summary(child_name, top_apps, total_seconds, view=None) -> None` (async)
  - `init_notifier(channel_id: int) -> DiscordNotifier`
  - `get_notifier() -> DiscordNotifier | None`

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_discord_notifier.py`:

```python
"""Tests for DiscordNotifier service."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


@pytest.fixture()
def notifier():
    from familylink_server.services.discord_notifier import DiscordNotifier
    return DiscordNotifier(channel_id=111)


@pytest.fixture()
def channel():
    ch = AsyncMock(spec=discord.TextChannel)
    ch.name = 'family-alerts'
    return ch


async def test_notify_change_no_op_before_channel_set(notifier):
    # Should not raise, just silently skip
    await notifier.notify_change('block', 'Emma', 'TikTok', 'web UI')


async def test_notify_change_sends_embed(notifier, channel):
    notifier.set_channel(channel)
    await notifier.notify_change('block', 'Emma', 'TikTok', 'web UI')
    channel.send.assert_awaited_once()
    call_kwargs = channel.send.call_args.kwargs
    assert 'embed' in call_kwargs
    assert call_kwargs['embed'].title is not None


async def test_notify_change_passes_view(notifier, channel):
    notifier.set_channel(channel)
    view = MagicMock(spec=discord.ui.View)
    await notifier.notify_change('lock', 'Emma', 'device-1', 'bot', view=view)
    call_kwargs = channel.send.call_args.kwargs
    assert call_kwargs['view'] is view


async def test_post_daily_summary_sends_embed(notifier, channel):
    notifier.set_channel(channel)
    top_apps = [
        {'title': 'YouTube', 'seconds': 6300},
        {'title': 'Minecraft', 'seconds': 3480},
    ]
    await notifier.post_daily_summary('Emma', top_apps, total_seconds=9780)
    channel.send.assert_awaited_once()
    call_kwargs = channel.send.call_args.kwargs
    assert 'embed' in call_kwargs


def test_init_notifier_sets_singleton():
    from familylink_server.services import discord_notifier as mod
    mod._notifier = None
    notifier = mod.init_notifier(999)
    assert mod.get_notifier() is notifier
    assert notifier._channel_id == 999
    mod._notifier = None  # cleanup
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/server/test_discord_notifier.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` (file doesn't exist yet).

- [ ] **Step 3: Create `src/familylink_server/services/discord_notifier.py`**

```python
"""Outbound Discord notification service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _change_embed(action: str, child_name: str, target: str, source: str) -> discord.Embed:
    """Build a change-alert embed.  Full embed builder lives in bot.embeds once that module exists."""
    action_map = {
        'block': ('🔒 App Blocked', discord.Color.red()),
        'always_allow': ('✅ App Always Allowed', discord.Color.green()),
        'set_limit': ('⏱️ App Limit Set', discord.Color.orange()),
        'lock_device': ('🔒 Device Locked', discord.Color.orange()),
        'unlock_device': ('🔓 Device Unlocked', discord.Color.green()),
    }
    title, color = action_map.get(action, (f'ℹ️ {action.replace("_", " ").title()}', discord.Color.blurple()))
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name='Child', value=child_name, inline=True)
    embed.add_field(name='Target', value=target, inline=True)
    embed.add_field(name='By', value=source, inline=True)
    return embed


def _summary_embed(child_name: str, top_apps: list[dict], total_seconds: int) -> discord.Embed:
    """Build a daily summary embed."""
    import datetime
    today = datetime.date.today().strftime('%A %-d %b')
    h, rem = divmod(total_seconds, 3600)
    m = rem // 60
    total_str = f'{h}h {m:02d}m' if h else f'{m}m'
    embed = discord.Embed(
        title=f'📊 Daily Summary — {child_name}  ·  {today}',
        description=f'Total screen time: **{total_str}**',
        color=discord.Color.blurple(),
    )
    max_s = max((a['seconds'] for a in top_apps), default=1)
    for app in top_apps[:5]:
        ah, ar = divmod(app['seconds'], 3600)
        am = ar // 60
        dur = f'{ah}h {am:02d}m' if ah else f'{am}m'
        filled = round(app['seconds'] / max_s * 10)
        bar = '█' * filled + '░' * (10 - filled)
        embed.add_field(name=app['title'], value=f'`{bar}` {dur}', inline=False)
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
        view: discord.ui.View | None = None,
    ) -> None:
        """Post a daily usage summary embed. No-op if channel not yet ready."""
        if self._channel is None:
            return
        embed = _summary_embed(child_name, top_apps, total_seconds)
        await self._channel.send(embed=embed, view=view)


_notifier: DiscordNotifier | None = None


def init_notifier(channel_id: int) -> DiscordNotifier:
    """Create and store the singleton. Called once in lifespan."""
    global _notifier
    _notifier = DiscordNotifier(channel_id)
    return _notifier


def get_notifier() -> DiscordNotifier | None:
    """Return the singleton, or None when Discord is disabled."""
    return _notifier
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/server/test_discord_notifier.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/services/discord_notifier.py tests/server/test_discord_notifier.py
git commit -m "feat: add DiscordNotifier service"
```

---

## Task 3: Embed Builders

**Files:**
- Create: `src/familylink_server/bot/__init__.py`
- Create: `src/familylink_server/bot/embeds.py`
- Create: `tests/server/test_bot_embeds.py`

**Interfaces:**
- Produces:
  - `change_embed(action, child_name, target, source) -> discord.Embed`
  - `apps_list_embed(apps, child_name, page, total_pages) -> discord.Embed`
  - `devices_list_embed(devices, child_name) -> discord.Embed`
  - `usage_today_embed(child_name, top_apps, total_seconds) -> discord.Embed`
  - `usage_history_embed(child_name, daily_totals, days) -> discord.Embed`
  - `status_embed(children_data) -> discord.Embed`
  - `daily_summary_embed(child_name, top_apps, total_seconds) -> discord.Embed`

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_bot_embeds.py`:

```python
"""Tests for bot embed builder functions."""

import discord
import pytest


@pytest.fixture(autouse=True)
def _ensure_bot_package(tmp_path):
    """Ensure bot package exists (no-op once Task 3 is done)."""


def test_change_embed_block():
    from familylink_server.bot.embeds import change_embed
    embed = change_embed('block', 'Emma', 'TikTok', 'web UI')
    assert '🔒' in embed.title
    assert 'Blocked' in embed.title
    assert embed.color == discord.Color.red()
    fields = {f.name: f.value for f in embed.fields}
    assert fields['Child'] == 'Emma'
    assert fields['Target'] == 'TikTok'
    assert fields['By'] == 'web UI'


def test_change_embed_always_allow():
    from familylink_server.bot.embeds import change_embed
    embed = change_embed('always_allow', 'Emma', 'YouTube', 'bot')
    assert embed.color == discord.Color.green()


def test_change_embed_set_limit():
    from familylink_server.bot.embeds import change_embed
    embed = change_embed('set_limit', 'Emma', 'Minecraft', 'web UI')
    assert embed.color == discord.Color.orange()


def test_apps_list_embed():
    from familylink_server.bot.embeds import apps_list_embed
    apps = [
        {'title': 'YouTube', 'state': 'limited', 'state_label': 'Limited 60 min', 'package_name': 'com.youtube'},
        {'title': 'TikTok', 'state': 'blocked', 'state_label': 'Blocked', 'package_name': 'com.tiktok'},
    ]
    embed = apps_list_embed(apps, child_name='Emma', page=1, total_pages=1)
    assert 'Emma' in embed.title
    assert len(embed.fields) == len(apps)


def test_devices_list_embed():
    from familylink_server.bot.embeds import devices_list_embed
    devices = [{'friendly_name': 'Emma Phone', 'device_id': 'd1', 'is_locked': False}]
    embed = devices_list_embed(devices, child_name='Emma')
    assert 'Emma' in embed.title
    assert len(embed.fields) == 1


def test_usage_today_embed_bar_chart():
    from familylink_server.bot.embeds import usage_today_embed
    top_apps = [{'title': 'YouTube', 'seconds': 6300}, {'title': 'Minecraft', 'seconds': 1800}]
    embed = usage_today_embed('Emma', top_apps, total_seconds=8100)
    assert 'Emma' in embed.title
    assert '█' in embed.description or any('█' in f.value for f in embed.fields)


def test_usage_history_embed():
    from familylink_server.bot.embeds import usage_history_embed
    daily = [{'date': '2026-06-24', 'seconds': 7200}, {'date': '2026-06-23', 'seconds': 5400}]
    embed = usage_history_embed('Emma', daily, days=7)
    assert 'Emma' in embed.title
    assert len(embed.fields) == 2


def test_status_embed():
    from familylink_server.bot.embeds import status_embed
    children_data = [
        {'name': 'Emma', 'total_seconds': 7200, 'device_count': 1},
        {'name': 'Tom', 'total_seconds': 3600, 'device_count': 2},
    ]
    embed = status_embed(children_data)
    assert len(embed.fields) == 2


def test_daily_summary_embed_bar():
    from familylink_server.bot.embeds import daily_summary_embed
    top_apps = [{'title': 'YouTube', 'seconds': 6300}, {'title': 'Minecraft', 'seconds': 3150}]
    embed = daily_summary_embed('Emma', top_apps, total_seconds=9450)
    assert 'Emma' in embed.title
    assert '3h' in embed.description or '2h' in embed.description
    assert any('█' in f.value for f in embed.fields)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/server/test_bot_embeds.py -v
```

Expected: `ModuleNotFoundError` — package doesn't exist yet.

- [ ] **Step 3: Create `src/familylink_server/bot/__init__.py`**

```python
"""Discord bot package."""
```

Also create the commands sub-package placeholder:

```bash
mkdir -p src/familylink_server/bot/commands
touch src/familylink_server/bot/commands/__init__.py
```

- [ ] **Step 4: Create `src/familylink_server/bot/embeds.py`**

```python
"""Discord embed builder functions."""

from __future__ import annotations

import datetime

import discord

_ACTION_MAP: dict[str, tuple[str, discord.Color]] = {
    'block': ('🔒 App Blocked', discord.Color.red()),
    'always_allow': ('✅ App Always Allowed', discord.Color.green()),
    'set_limit': ('⏱️ App Limit Set', discord.Color.orange()),
    'lock_device': ('🔒 Device Locked', discord.Color.orange()),
    'unlock_device': ('🔓 Device Unlocked', discord.Color.green()),
}


def _fmt(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f'{h}h {m:02d}m' if h else f'{m}m'


def _bar(value: int, max_value: int, width: int = 10) -> str:
    if max_value == 0:
        return '░' * width
    filled = round(value / max_value * width)
    return '█' * filled + '░' * (width - filled)


def change_embed(action: str, child_name: str, target: str, source: str) -> discord.Embed:
    """Return an embed describing a single Family Link write action."""
    title, color = _ACTION_MAP.get(
        action,
        (f'ℹ️ {action.replace("_", " ").title()}', discord.Color.blurple()),
    )
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name='Child', value=child_name, inline=True)
    embed.add_field(name='Target', value=target, inline=True)
    embed.add_field(name='By', value=source, inline=True)
    return embed


def apps_list_embed(
    apps: list[dict],
    child_name: str,
    page: int,
    total_pages: int,
) -> discord.Embed:
    """Return a paginated embed listing apps and their current state."""
    embed = discord.Embed(
        title=f'📱 Apps — {child_name}  (page {page}/{total_pages})',
        color=discord.Color.blurple(),
    )
    for app in apps:
        embed.add_field(
            name=app['title'],
            value=app['state_label'],
            inline=True,
        )
    return embed


def devices_list_embed(devices: list[dict], child_name: str) -> discord.Embed:
    """Return an embed listing devices and their lock state."""
    embed = discord.Embed(title=f'📱 Devices — {child_name}', color=discord.Color.blurple())
    for d in devices:
        lock_icon = '🔒' if d.get('is_locked') else '🔓'
        embed.add_field(
            name=d.get('friendly_name') or d['device_id'],
            value=lock_icon,
            inline=True,
        )
    return embed


def usage_today_embed(child_name: str, top_apps: list[dict], total_seconds: int) -> discord.Embed:
    """Return a bar-chart embed of today's top app usage."""
    today = datetime.date.today().strftime('%A %-d %b')
    embed = discord.Embed(
        title=f'📊 Today — {child_name}  ·  {today}',
        description=f'Total: **{_fmt(total_seconds)}**',
        color=discord.Color.blurple(),
    )
    max_s = max((a['seconds'] for a in top_apps), default=1)
    for app in top_apps[:10]:
        embed.add_field(
            name=app['title'],
            value=f'`{_bar(app["seconds"], max_s)}` {_fmt(app["seconds"])}',
            inline=False,
        )
    return embed


def usage_history_embed(child_name: str, daily_totals: list[dict], days: int) -> discord.Embed:
    """Return an embed with per-day usage totals."""
    embed = discord.Embed(
        title=f'📈 History — {child_name}  (last {days} days)',
        color=discord.Color.blurple(),
    )
    max_s = max((d['seconds'] for d in daily_totals), default=1)
    for day in daily_totals:
        embed.add_field(
            name=day['date'],
            value=f'`{_bar(day["seconds"], max_s)}` {_fmt(day["seconds"])}',
            inline=False,
        )
    return embed


def status_embed(children_data: list[dict]) -> discord.Embed:
    """Return a dashboard overview embed covering all children."""
    embed = discord.Embed(title='🏠 Family Status', color=discord.Color.blurple())
    for child in children_data:
        devices = f'{child["device_count"]} device(s)'
        embed.add_field(
            name=child['name'],
            value=f'{_fmt(child["total_seconds"])} today · {devices}',
            inline=False,
        )
    return embed


def daily_summary_embed(child_name: str, top_apps: list[dict], total_seconds: int) -> discord.Embed:
    """Return a daily summary embed (used by the scheduled task)."""
    today = datetime.date.today().strftime('%A %-d %b')
    embed = discord.Embed(
        title=f'📊 Daily Summary — {child_name}  ·  {today}',
        description=f'Total screen time: **{_fmt(total_seconds)}**',
        color=discord.Color.blurple(),
    )
    max_s = max((a['seconds'] for a in top_apps), default=1)
    for app in top_apps[:5]:
        embed.add_field(
            name=app['title'],
            value=f'`{_bar(app["seconds"], max_s)}` {_fmt(app["seconds"])}',
            inline=False,
        )
    return embed
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/server/test_bot_embeds.py -v
```

Expected: all embed tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/bot/__init__.py src/familylink_server/bot/embeds.py \
        src/familylink_server/bot/commands/__init__.py tests/server/test_bot_embeds.py
git commit -m "feat: add Discord embed builders"
```

---

## Task 4: Authorization + Child Resolution

**Files:**
- Modify: `src/familylink_server/bot/commands/__init__.py`
- Test in: `tests/server/test_bot_commands.py` (created in this task)

**Interfaces:**
- Produces:
  - `require_discord_role(interaction: discord.Interaction) -> bool`
  - `child_autocomplete(interaction, current) -> list[app_commands.Choice[str]]` (async)
  - `resolve_child(service, child_id) -> tuple[str, str] | None` (async) — returns `(user_id, display_name)` or `None` when ambiguous

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_bot_commands.py`:

```python
"""Tests for bot authorization and child resolution helpers."""

import os
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://localhost/familylink_test')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-32-bytes-exactly!')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'test-client-id')
os.environ.setdefault('GOOGLE_CLIENT_SECRET', 'test-client-secret')
os.environ.setdefault('FAMILYLINK_GOOGLE_EMAIL', 'parent@gmail.com')
os.environ.setdefault('FAMILYLINK_COOKIES_B64', 'dGVzdA==')
os.environ.setdefault('DISCORD_ALLOWED_ROLE', 'Parent')

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


def _make_interaction(role_names: list[str] | None = None) -> discord.Interaction:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    member = MagicMock(spec=discord.Member)
    roles = [MagicMock(spec=discord.Role) for _ in (role_names or [])]
    for role, name in zip(roles, (role_names or [])):
        role.name = name
    member.roles = roles
    interaction.user = member
    interaction.response = AsyncMock()
    return interaction


def test_require_discord_role_passes_with_role():
    from familylink_server.bot.commands import require_discord_role
    interaction = _make_interaction(['Parent', 'Member'])
    assert require_discord_role(interaction) is True


def test_require_discord_role_fails_without_role():
    from familylink_server.bot.commands import require_discord_role
    interaction = _make_interaction(['Member'])
    assert require_discord_role(interaction) is False


def test_require_discord_role_fails_no_guild():
    from familylink_server.bot.commands import require_discord_role
    interaction = _make_interaction(['Parent'])
    interaction.guild = None
    assert require_discord_role(interaction) is False


async def test_resolve_child_single_child():
    from familylink_server.bot.commands import resolve_child
    svc = AsyncMock()
    member = MagicMock()
    member.user_id = 'uid-1'
    member.profile.display_name = 'Emma'
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    result = await resolve_child(svc, None)
    assert result == ('uid-1', 'Emma')


async def test_resolve_child_multiple_children_no_id():
    from familylink_server.bot.commands import resolve_child
    svc = AsyncMock()
    m1, m2 = MagicMock(), MagicMock()
    for m, uid, name in [(m1, 'uid-1', 'Emma'), (m2, 'uid-2', 'Tom')]:
        m.user_id = uid
        m.profile.display_name = name
        m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m1, m2])

    result = await resolve_child(svc, None)
    assert result is None  # ambiguous


async def test_resolve_child_explicit_id():
    from familylink_server.bot.commands import resolve_child
    svc = AsyncMock()
    member = MagicMock()
    member.user_id = 'uid-1'
    member.profile.display_name = 'Emma'
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    result = await resolve_child(svc, 'uid-1')
    assert result == ('uid-1', 'Emma')
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/server/test_bot_commands.py -v
```

Expected: ImportError — functions not defined yet.

- [ ] **Step 3: Write `src/familylink_server/bot/commands/__init__.py`**

```python
"""Shared helpers for bot command modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from familylink_server.config import settings

if TYPE_CHECKING:
    from familylink_server.services.family_link import FamilyLinkService


def require_discord_role(interaction: discord.Interaction) -> bool:
    """Return True when the invoking member has the configured Discord role."""
    if interaction.guild is None:
        return False
    if not isinstance(interaction.user, discord.Member):
        return False
    allowed = settings.discord_allowed_role
    return any(role.name == allowed for role in interaction.user.roles)


async def child_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete choices for the optional child parameter."""
    from familylink_server.services.family_link import get_service
    svc = get_service()
    members = await svc.get_members()
    supervised = [
        m for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    return [
        app_commands.Choice(name=m.profile.display_name, value=m.user_id)
        for m in supervised
        if current.lower() in m.profile.display_name.lower()
    ]


async def resolve_child(
    service: FamilyLinkService,
    child_id: str | None,
) -> tuple[str, str] | None:
    """Resolve optional child_id to (user_id, display_name).

    Returns None when child_id is None and there are multiple children (caller
    should reply with an ephemeral error asking the user to specify).
    """
    members = await service.get_members()
    supervised = [
        m for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    if child_id:
        for m in supervised:
            if m.user_id == child_id:
                return (m.user_id, m.profile.display_name)
        return None
    if len(supervised) == 1:
        m = supervised[0]
        return (m.user_id, m.profile.display_name)
    return None
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/server/test_bot_commands.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/bot/commands/__init__.py tests/server/test_bot_commands.py
git commit -m "feat: add Discord bot authorization and child resolution helpers"
```

---

## Task 5: Bot Client + Lifespan Integration

**Files:**
- Create: `src/familylink_server/bot/client.py`
- Modify: `src/familylink_server/main.py`
- Test: add to `tests/server/test_main.py`

**Interfaces:**
- Consumes: `settings.discord_enabled`, `settings.discord_bot_token`, `settings.discord_guild_id`, `settings.discord_channel_id`, `settings.discord_summary_time_parsed`, `get_service()`, `init_notifier()`, `get_notifier()`
- Produces: `FamilyLinkBot(service, notifier, guild_id, summary_time)` — `commands.Bot` subclass with `setup_hook` + `on_ready` + `_run_daily_summary`

- [ ] **Step 1: Write failing tests**

Add to `tests/server/test_main.py` (or create it if it only has import tests):

```python
async def test_bot_not_started_when_discord_disabled(monkeypatch):
    """Lifespan should not create a bot task when Discord vars are absent."""
    import asyncio
    from unittest.mock import patch, AsyncMock

    monkeypatch.delenv('DISCORD_BOT_TOKEN', raising=False)
    monkeypatch.delenv('DISCORD_GUILD_ID', raising=False)
    monkeypatch.delenv('DISCORD_CHANNEL_ID', raising=False)

    with patch('familylink_server.main.init_service'), \
         patch('familylink_server.main.asyncio.create_task') as mock_create_task:
        from familylink_server.main import lifespan, app
        async with lifespan(app):
            pass
        mock_create_task.assert_not_called()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/server/test_main.py::test_bot_not_started_when_discord_disabled -v
```

Expected: FAIL (lifespan doesn't call create_task yet, but the mock import will fail if lifespan doesn't import asyncio in the right place).

- [ ] **Step 3: Create `src/familylink_server/bot/client.py`**

```python
"""Discord bot client and restart wrapper."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from familylink_server.bot.embeds import daily_summary_embed

if TYPE_CHECKING:
    import datetime

    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

logger = logging.getLogger(__name__)


class FamilyLinkBot(commands.Bot):
    """discord.py Bot subclass that wires in FamilyLinkService and DiscordNotifier."""

    def __init__(
        self,
        service: FamilyLinkService,
        notifier: DiscordNotifier,
        guild_id: int,
        summary_time: datetime.time,
    ) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix='!', intents=intents)
        self.service = service
        self.notifier = notifier
        self.guild_id = guild_id
        self._summary_time = summary_time

    async def setup_hook(self) -> None:
        """Register command groups and create the scheduled task."""
        from familylink_server.bot.commands.apps import AppsGroup
        from familylink_server.bot.commands.devices import DevicesGroup
        from familylink_server.bot.commands.usage import UsageGroup, make_status_command, make_refresh_command

        guild = discord.Object(id=self.guild_id)
        self.tree.add_command(AppsGroup(self.service, self.notifier), guild=guild)
        self.tree.add_command(DevicesGroup(self.service, self.notifier), guild=guild)
        self.tree.add_command(UsageGroup(self.service, self.notifier), guild=guild)
        self.tree.add_command(make_status_command(self.service), guild=guild)
        self.tree.add_command(make_refresh_command(self.service), guild=guild)

        self.daily_summary_task = tasks.loop(time=self._summary_time)(self._run_daily_summary)

        @self.tree.error
        async def on_tree_error(
            interaction: discord.Interaction,
            error: app_commands.AppCommandError,
        ) -> None:
            if isinstance(error, app_commands.CheckFailure):
                await interaction.response.send_message(
                    f'You need the **{self.notifier._channel_id and ""}** role to use this command.',
                    ephemeral=True,
                )
            else:
                logger.exception('Unhandled app command error', exc_info=error)

    async def on_ready(self) -> None:
        """Sync command tree, resolve channel, start summary task."""
        guild = discord.Object(id=self.guild_id)
        await self.tree.sync(guild=guild)
        logger.info('Discord bot ready as %s — commands synced to guild %s', self.user, self.guild_id)

        channel = self.get_channel(self.notifier._channel_id)
        if isinstance(channel, discord.TextChannel):
            self.notifier.set_channel(channel)
        else:
            logger.warning('Discord channel %s not found or not a text channel', self.notifier._channel_id)

        if not self.daily_summary_task.is_running():
            self.daily_summary_task.start()

    async def _run_daily_summary(self) -> None:
        """Post a daily usage summary embed for each supervised child."""
        from familylink_server.bot.views import SummaryView

        try:
            members = await self.service.get_members()
            supervised = [
                m for m in members.members
                if m.member_supervision_info and m.member_supervision_info.is_supervised_member
            ]
            for child in supervised:
                usage = await self.service.get_apps_and_usage(child.user_id)
                top_apps = sorted(
                    [
                        {'title': app.title, 'seconds': app.usage_today_seconds}
                        for app in usage.apps
                        if hasattr(app, 'usage_today_seconds') and app.usage_today_seconds
                    ],
                    key=lambda x: x['seconds'],
                    reverse=True,
                )[:5]
                total_seconds = sum(a['seconds'] for a in top_apps)
                device_id = usage.device_info[0].device_id if usage.device_info else None
                view = SummaryView(self.service, self.notifier, child.user_id, child.profile.display_name, device_id)
                await self.notifier.post_daily_summary(
                    child.profile.display_name, top_apps, total_seconds, view=view
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

- [ ] **Step 4: Modify `src/familylink_server/main.py` to start the bot in lifespan**

```python
"""FastAPI application factory."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from familylink_server.auth.oauth import router as auth_router
from familylink_server.config import settings
from familylink_server.routers.apps import router as apps_router
from familylink_server.routers.dashboard import router as dashboard_router
from familylink_server.routers.devices import router as devices_router
from familylink_server.routers.history import router as history_router
from familylink_server.routers.members import router as members_router
from familylink_server.routers.usage import router as usage_router
from familylink_server.services.family_link import init_service, get_service

logger = logging.getLogger(__name__)


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
        logger.info('Discord bot disabled (DISCORD_BOT_TOKEN / GUILD_ID / CHANNEL_ID not set)')

    yield

    if bot_task is not None:
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task


app = FastAPI(
    title='FamilyLink',
    description='Google Family Link management web service',
    lifespan=lifespan,
)

app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(history_router)
app.include_router(apps_router)
app.include_router(members_router)
app.include_router(usage_router)
app.include_router(devices_router)

_static = Path(__file__).parent / 'static'
if _static.exists():
    app.mount('/static', StaticFiles(directory=str(_static)), name='static')
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/server/test_main.py -v
```

Expected: PASS (including the new `test_bot_not_started_when_discord_disabled` test).

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/bot/client.py src/familylink_server/main.py tests/server/test_main.py
git commit -m "feat: add FamilyLinkBot client and wire into FastAPI lifespan"
```

---

## Task 6: Action Views

**Files:**
- Create: `src/familylink_server/bot/views.py`
- Create: `tests/server/test_bot_views.py`

**Interfaces:**
- Consumes: `FamilyLinkService`, `DiscordNotifier`, `require_discord_role`
- Produces:
  - `AppBlockView(svc, notifier, package, child_id, child_name)` — Unblock + Always Allow buttons
  - `AppLimitView(svc, notifier, package, child_id, child_name)` — Undo (always allow) button
  - `AppAllowView(svc, notifier, package, child_id, child_name)` — Remove (block) button
  - `DeviceLockView(svc, notifier, device_id, child_id, child_name)` — Unlock button
  - `DeviceUnlockView(svc, notifier, device_id, child_id, child_name)` — Lock button
  - `SummaryView(svc, notifier, child_id, child_name, device_id)` — Lock Device button

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_bot_views.py`:

```python
"""Tests for Discord UI action views."""

import os
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://localhost/familylink_test')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-32-bytes-exactly!')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'test-client-id')
os.environ.setdefault('GOOGLE_CLIENT_SECRET', 'test-client-secret')
os.environ.setdefault('FAMILYLINK_GOOGLE_EMAIL', 'parent@gmail.com')
os.environ.setdefault('FAMILYLINK_COOKIES_B64', 'dGVzdA==')
os.environ.setdefault('DISCORD_ALLOWED_ROLE', 'Parent')

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest


def _make_interaction(role_names=('Parent',)):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    member = MagicMock(spec=discord.Member)
    roles = [MagicMock(spec=discord.Role, name=n) for n in role_names]
    for role, name in zip(roles, role_names):
        role.name = name
    member.roles = roles
    interaction.user = member
    interaction.response = AsyncMock()
    return interaction


async def test_app_block_view_unblock_calls_service():
    from familylink_server.bot.views import AppBlockView
    svc = AsyncMock()
    notifier = AsyncMock()
    view = AppBlockView(svc, notifier, 'com.tiktok', 'uid-1', 'Emma')

    interaction = _make_interaction()
    await view._unblock(interaction, MagicMock())

    svc.always_allow_app.assert_awaited_once_with('com.tiktok', child_id='uid-1')
    interaction.response.send_message.assert_awaited_once()


async def test_app_block_view_always_allow_calls_service():
    from familylink_server.bot.views import AppBlockView
    svc = AsyncMock()
    notifier = AsyncMock()
    view = AppBlockView(svc, notifier, 'com.tiktok', 'uid-1', 'Emma')

    interaction = _make_interaction()
    await view._always_allow(interaction, MagicMock())

    svc.always_allow_app.assert_awaited_once_with('com.tiktok', child_id='uid-1')


async def test_device_lock_view_unlock_calls_service():
    from familylink_server.bot.views import DeviceLockView
    svc = AsyncMock()
    notifier = AsyncMock()
    view = DeviceLockView(svc, notifier, 'd-1', 'uid-1', 'Emma')

    interaction = _make_interaction()
    await view._unlock(interaction, MagicMock())

    svc.unlock_device.assert_awaited_once_with('d-1', child_id='uid-1')


async def test_summary_view_lock_device_calls_service():
    from familylink_server.bot.views import SummaryView
    svc = AsyncMock()
    notifier = AsyncMock()
    view = SummaryView(svc, notifier, 'uid-1', 'Emma', 'd-1')

    interaction = _make_interaction()
    await view._lock_device(interaction, MagicMock())

    svc.lock_device.assert_awaited_once_with('d-1', child_id='uid-1')


async def test_app_block_view_unauthorized():
    from familylink_server.bot.views import AppBlockView
    svc = AsyncMock()
    notifier = AsyncMock()
    view = AppBlockView(svc, notifier, 'com.tiktok', 'uid-1', 'Emma')

    interaction = _make_interaction(role_names=('Member',))
    await view._unblock(interaction, MagicMock())

    svc.always_allow_app.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.call_args.kwargs
    assert msg.get('ephemeral') is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/server/test_bot_views.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create `src/familylink_server/bot/views.py`**

```python
"""Discord UI views (action button rows for embeds)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from familylink_server.bot.commands import require_discord_role

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

_TIMEOUT = 300


class AppBlockView(discord.ui.View):
    """Buttons shown after blocking an app: Unblock and Always Allow."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        package: str,
        child_id: str,
        child_name: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._package = package
        self._child_id = child_id
        self._child_name = child_name

    @discord.ui.button(label='Unblock', style=discord.ButtonStyle.success)
    async def _unblock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        await self._svc.always_allow_app(self._package, child_id=self._child_id)
        await self._notifier.notify_change('always_allow', self._child_name, self._package, interaction.user.display_name)
        await interaction.response.send_message(f'✅ {self._package} unblocked for {self._child_name}.', ephemeral=True)
        self.stop()

    @discord.ui.button(label='Always Allow', style=discord.ButtonStyle.primary)
    async def _always_allow(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        await self._svc.always_allow_app(self._package, child_id=self._child_id)
        await self._notifier.notify_change('always_allow', self._child_name, self._package, interaction.user.display_name)
        await interaction.response.send_message(f'✅ {self._package} always allowed for {self._child_name}.', ephemeral=True)
        self.stop()


class AppLimitView(discord.ui.View):
    """Button shown after setting an app limit: Undo (removes limit via always_allow)."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        package: str,
        child_id: str,
        child_name: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._package = package
        self._child_id = child_id
        self._child_name = child_name

    @discord.ui.button(label='Undo', style=discord.ButtonStyle.secondary)
    async def _undo(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        await self._svc.always_allow_app(self._package, child_id=self._child_id)
        await self._notifier.notify_change('always_allow', self._child_name, self._package, interaction.user.display_name)
        await interaction.response.send_message(f'↩️ Limit removed for {self._package}.', ephemeral=True)
        self.stop()


class AppAllowView(discord.ui.View):
    """Button shown after always-allowing an app: Remove (blocks it)."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        package: str,
        child_id: str,
        child_name: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._package = package
        self._child_id = child_id
        self._child_name = child_name

    @discord.ui.button(label='Remove', style=discord.ButtonStyle.danger)
    async def _remove(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        await self._svc.block_app(self._package, child_id=self._child_id)
        await self._notifier.notify_change('block', self._child_name, self._package, interaction.user.display_name)
        await interaction.response.send_message(f'🔒 {self._package} blocked for {self._child_name}.', ephemeral=True)
        self.stop()


class DeviceLockView(discord.ui.View):
    """Button shown after locking a device: Unlock."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        device_id: str,
        child_id: str,
        child_name: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._device_id = device_id
        self._child_id = child_id
        self._child_name = child_name

    @discord.ui.button(label='Unlock', style=discord.ButtonStyle.success)
    async def _unlock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        await self._svc.unlock_device(self._device_id, child_id=self._child_id)
        await self._notifier.notify_change('unlock_device', self._child_name, self._device_id, interaction.user.display_name)
        await interaction.response.send_message('🔓 Device unlocked.', ephemeral=True)
        self.stop()


class DeviceUnlockView(discord.ui.View):
    """Button shown after unlocking a device: Lock."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        device_id: str,
        child_id: str,
        child_name: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._device_id = device_id
        self._child_id = child_id
        self._child_name = child_name

    @discord.ui.button(label='Lock', style=discord.ButtonStyle.danger)
    async def _lock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        await self._svc.lock_device(self._device_id, child_id=self._child_id)
        await self._notifier.notify_change('lock_device', self._child_name, self._device_id, interaction.user.display_name)
        await interaction.response.send_message('🔒 Device locked.', ephemeral=True)
        self.stop()


class SummaryView(discord.ui.View):
    """Buttons on the daily summary embed: Lock Device."""

    def __init__(
        self,
        svc: FamilyLinkService,
        notifier: DiscordNotifier,
        child_id: str,
        child_name: str,
        device_id: str | None,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._svc = svc
        self._notifier = notifier
        self._child_id = child_id
        self._child_name = child_name
        self._device_id = device_id

    @discord.ui.button(label='Lock Device', style=discord.ButtonStyle.danger)
    async def _lock_device(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        if not self._device_id:
            await interaction.response.send_message('No device found for this child.', ephemeral=True)
            return
        await self._svc.lock_device(self._device_id, child_id=self._child_id)
        await self._notifier.notify_change('lock_device', self._child_name, self._device_id, interaction.user.display_name)
        await interaction.response.send_message('🔒 Device locked.', ephemeral=True)
        self.stop()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/server/test_bot_views.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/bot/views.py tests/server/test_bot_views.py
git commit -m "feat: add Discord action button views"
```

---

## Task 7: /apps Command Group

**Files:**
- Create: `src/familylink_server/bot/commands/apps.py`
- Test: add to `tests/server/test_bot_commands.py`

**Interfaces:**
- Consumes: `FamilyLinkService`, `DiscordNotifier`, `require_discord_role`, `child_autocomplete`, `resolve_child`, embed builders, `AppBlockView`, `AppLimitView`, `AppAllowView`
- Produces: `AppsGroup(app_commands.Group)` with subcommands: `list`, `limit`, `block`, `allow`

- [ ] **Step 1: Write failing tests**

Append to `tests/server/test_bot_commands.py`:

```python
async def test_apps_block_calls_service():
    from familylink_server.bot.commands.apps import AppsGroup
    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier)

    # Single child, no child_id needed
    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(['Parent'])
    await group.block.callback(group, interaction, package='com.tiktok', child='uid-1')

    svc.block_app.assert_awaited_once_with('com.tiktok', child_id='uid-1')
    interaction.response.send_message.assert_awaited_once()


async def test_apps_limit_calls_service():
    from familylink_server.bot.commands.apps import AppsGroup
    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier)

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(['Parent'])
    await group.limit.callback(group, interaction, package='com.youtube', minutes=60, child='uid-1')

    svc.set_app_limit.assert_awaited_once_with('com.youtube', 60, child_id='uid-1')


async def test_apps_allow_calls_service():
    from familylink_server.bot.commands.apps import AppsGroup
    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier)

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(['Parent'])
    await group.allow.callback(group, interaction, package='com.youtube', child='uid-1')

    svc.always_allow_app.assert_awaited_once_with('com.youtube', child_id='uid-1')


async def test_apps_block_unauthorized():
    from familylink_server.bot.commands.apps import AppsGroup
    svc = AsyncMock()
    notifier = AsyncMock()
    group = AppsGroup(svc, notifier)

    interaction = _make_interaction(['Member'])
    await group.block.callback(group, interaction, package='com.tiktok', child='uid-1')

    svc.block_app.assert_not_awaited()
    msg = interaction.response.send_message.call_args.kwargs
    assert msg.get('ephemeral') is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/server/test_bot_commands.py::test_apps_block_calls_service -v
```

Expected: ImportError.

- [ ] **Step 3: Create `src/familylink_server/bot/commands/apps.py`**

```python
"""Discord /apps command group."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from familylink_server.bot.commands import child_autocomplete, require_discord_role, resolve_child
from familylink_server.bot.embeds import apps_list_embed

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

_PAGE_SIZE = 10


class AppsGroup(app_commands.Group, name='apps', description='Manage supervised apps'):
    """Slash command group: /apps list | limit | block | allow."""

    def __init__(self, service: FamilyLinkService, notifier: DiscordNotifier) -> None:
        super().__init__()
        self._svc = service
        self._notifier = notifier

    @app_commands.command(name='list', description='List apps and their current state for a child')
    @app_commands.describe(child='Which child (required when supervising multiple children)', page='Page number')
    @app_commands.autocomplete(child=child_autocomplete)
    async def list(self, interaction: discord.Interaction, child: str | None = None, page: int = 1) -> None:
        """List paginated apps."""
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message('Please specify a child with the `child` parameter.', ephemeral=True)
            return
        child_id, child_name = resolved
        usage = await self._svc.get_apps_and_usage(child_id)
        all_apps = sorted(
            [
                {
                    'title': a.title,
                    'package_name': a.package_name,
                    'state': 'blocked' if a.supervision_setting.hidden else (
                        'limited' if a.supervision_setting.usage_limit else (
                            'allowed' if a.supervision_setting.always_allowed_app_info else 'unmanaged'
                        )
                    ),
                    'state_label': 'Blocked' if a.supervision_setting.hidden else (
                        f'Limited {a.supervision_setting.usage_limit.daily_usage_limit_mins} min'
                        if a.supervision_setting.usage_limit else (
                            'Always allowed' if a.supervision_setting.always_allowed_app_info else 'Unmanaged'
                        )
                    ),
                }
                for a in usage.apps
            ],
            key=lambda x: x['title'].lower(),
        )
        total_pages = max(1, (len(all_apps) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        page = max(1, min(page, total_pages))
        page_apps = all_apps[(page - 1) * _PAGE_SIZE: page * _PAGE_SIZE]
        embed = apps_list_embed(page_apps, child_name, page, total_pages)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='limit', description='Set a daily time limit for an app')
    @app_commands.describe(package='App package name (e.g. com.zhiliaoapp.musically)', minutes='Daily limit in minutes', child='Which child')
    @app_commands.autocomplete(child=child_autocomplete)
    async def limit(self, interaction: discord.Interaction, package: str, minutes: int, child: str | None = None) -> None:
        """Set a daily usage limit."""
        from familylink_server.bot.views import AppLimitView
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message('Please specify a child with the `child` parameter.', ephemeral=True)
            return
        child_id, child_name = resolved
        await self._svc.set_app_limit(package, minutes, child_id=child_id)
        await self._notifier.notify_change('set_limit', child_name, f'{package} ({minutes} min)', interaction.user.display_name)
        view = AppLimitView(self._svc, self._notifier, package, child_id, child_name)
        await interaction.response.send_message(
            f'⏱️ Limit set: **{minutes} min/day** for `{package}` ({child_name}).',
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name='block', description='Block an app for a child')
    @app_commands.describe(package='App package name', child='Which child')
    @app_commands.autocomplete(child=child_autocomplete)
    async def block(self, interaction: discord.Interaction, package: str, child: str | None = None) -> None:
        """Block an app."""
        from familylink_server.bot.views import AppBlockView
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message('Please specify a child with the `child` parameter.', ephemeral=True)
            return
        child_id, child_name = resolved
        await self._svc.block_app(package, child_id=child_id)
        await self._notifier.notify_change('block', child_name, package, interaction.user.display_name)
        view = AppBlockView(self._svc, self._notifier, package, child_id, child_name)
        await interaction.response.send_message(
            f'🔒 `{package}` blocked for {child_name}.',
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name='allow', description='Always allow an app for a child')
    @app_commands.describe(package='App package name', child='Which child')
    @app_commands.autocomplete(child=child_autocomplete)
    async def allow(self, interaction: discord.Interaction, package: str, child: str | None = None) -> None:
        """Always-allow an app."""
        from familylink_server.bot.views import AppAllowView
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message('Please specify a child with the `child` parameter.', ephemeral=True)
            return
        child_id, child_name = resolved
        await self._svc.always_allow_app(package, child_id=child_id)
        await self._notifier.notify_change('always_allow', child_name, package, interaction.user.display_name)
        view = AppAllowView(self._svc, self._notifier, package, child_id, child_name)
        await interaction.response.send_message(
            f'✅ `{package}` always allowed for {child_name}.',
            view=view,
            ephemeral=True,
        )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/server/test_bot_commands.py -v
```

Expected: all tests PASS (including the new apps tests).

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/bot/commands/apps.py tests/server/test_bot_commands.py
git commit -m "feat: add Discord /apps command group"
```

---

## Task 8: /devices Command Group

**Files:**
- Create: `src/familylink_server/bot/commands/devices.py`
- Test: add to `tests/server/test_bot_commands.py`

**Interfaces:**
- Consumes: same helpers as Task 7; `DeviceLockView`, `DeviceUnlockView`
- Produces: `DevicesGroup(app_commands.Group)` with subcommands: `list`, `lock`, `unlock`

- [ ] **Step 1: Write failing tests**

Append to `tests/server/test_bot_commands.py`:

```python
async def test_devices_lock_calls_service():
    from familylink_server.bot.commands.devices import DevicesGroup
    svc = AsyncMock()
    notifier = AsyncMock()
    group = DevicesGroup(svc, notifier)

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(['Parent'])
    await group.lock.callback(group, interaction, device='d-1', child='uid-1')

    svc.lock_device.assert_awaited_once_with('d-1', child_id='uid-1')
    interaction.response.send_message.assert_awaited_once()


async def test_devices_unlock_calls_service():
    from familylink_server.bot.commands.devices import DevicesGroup
    svc = AsyncMock()
    notifier = AsyncMock()
    group = DevicesGroup(svc, notifier)

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    interaction = _make_interaction(['Parent'])
    await group.unlock.callback(group, interaction, device='d-1', child='uid-1')

    svc.unlock_device.assert_awaited_once_with('d-1', child_id='uid-1')
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/server/test_bot_commands.py::test_devices_lock_calls_service -v
```

Expected: ImportError.

- [ ] **Step 3: Create `src/familylink_server/bot/commands/devices.py`**

```python
"""Discord /devices command group."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from familylink_server.bot.commands import child_autocomplete, require_discord_role, resolve_child
from familylink_server.bot.embeds import devices_list_embed

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService


class DevicesGroup(app_commands.Group, name='devices', description='Manage supervised devices'):
    """Slash command group: /devices list | lock | unlock."""

    def __init__(self, service: FamilyLinkService, notifier: DiscordNotifier) -> None:
        super().__init__()
        self._svc = service
        self._notifier = notifier

    @app_commands.command(name='list', description='List devices and their lock state for a child')
    @app_commands.describe(child='Which child')
    @app_commands.autocomplete(child=child_autocomplete)
    async def list(self, interaction: discord.Interaction, child: str | None = None) -> None:
        """List devices."""
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message('Please specify a child with the `child` parameter.', ephemeral=True)
            return
        child_id, child_name = resolved
        usage = await self._svc.get_apps_and_usage(child_id)
        devices = [
            {
                'device_id': d.device_id,
                'friendly_name': d.display_info.friendly_name,
                'is_locked': False,
            }
            for d in usage.device_info
        ]
        embed = devices_list_embed(devices, child_name)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='lock', description='Lock a device')
    @app_commands.describe(device='Device ID', child='Which child')
    @app_commands.autocomplete(child=child_autocomplete)
    async def lock(self, interaction: discord.Interaction, device: str, child: str | None = None) -> None:
        """Lock a device."""
        from familylink_server.bot.views import DeviceLockView
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message('Please specify a child with the `child` parameter.', ephemeral=True)
            return
        child_id, child_name = resolved
        await self._svc.lock_device(device, child_id=child_id)
        await self._notifier.notify_change('lock_device', child_name, device, interaction.user.display_name)
        view = DeviceLockView(self._svc, self._notifier, device, child_id, child_name)
        await interaction.response.send_message(f'🔒 Device `{device}` locked for {child_name}.', view=view, ephemeral=True)

    @app_commands.command(name='unlock', description='Unlock a device')
    @app_commands.describe(device='Device ID', child='Which child')
    @app_commands.autocomplete(child=child_autocomplete)
    async def unlock(self, interaction: discord.Interaction, device: str, child: str | None = None) -> None:
        """Unlock a device."""
        from familylink_server.bot.views import DeviceUnlockView
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message('Please specify a child with the `child` parameter.', ephemeral=True)
            return
        child_id, child_name = resolved
        await self._svc.unlock_device(device, child_id=child_id)
        await self._notifier.notify_change('unlock_device', child_name, device, interaction.user.display_name)
        view = DeviceUnlockView(self._svc, self._notifier, device, child_id, child_name)
        await interaction.response.send_message(f'🔓 Device `{device}` unlocked for {child_name}.', view=view, ephemeral=True)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/server/test_bot_commands.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/bot/commands/devices.py tests/server/test_bot_commands.py
git commit -m "feat: add Discord /devices command group"
```

---

## Task 9: /usage, /status, /refresh Commands

**Files:**
- Create: `src/familylink_server/bot/commands/usage.py`
- Test: add to `tests/server/test_bot_commands.py`

**Interfaces:**
- Consumes: `FamilyLinkService`, `DiscordNotifier` (passed to StatusCommand/RefreshCommand for consistency), embed builders
- Produces:
  - `UsageGroup(app_commands.Group)` with subcommands: `today`, `history`
  - `make_status_command(service) -> app_commands.Command` — factory for top-level `/status`
  - `make_refresh_command(service) -> app_commands.Command` — factory for top-level `/refresh`

- [ ] **Step 1: Write failing tests**

Append to `tests/server/test_bot_commands.py`:

```python
async def test_usage_today_calls_service():
    from familylink_server.bot.commands.usage import UsageGroup
    svc = AsyncMock()
    notifier = AsyncMock()
    group = UsageGroup(svc, notifier)

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    app_mock = MagicMock()
    app_mock.title = 'YouTube'
    app_mock.usage_today_seconds = 3600
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app_mock])

    interaction = _make_interaction(['Parent'])
    await group.today.callback(group, interaction, child='uid-1')

    svc.get_apps_and_usage.assert_awaited_once_with('uid-1')
    interaction.response.send_message.assert_awaited_once()


async def test_status_calls_service():
    from familylink_server.bot.commands.usage import make_status_command
    svc = AsyncMock()
    cmd = make_status_command(svc)

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])
    svc.get_apps_and_usage.return_value = MagicMock(apps=[], device_info=[])

    interaction = _make_interaction(['Parent'])
    await cmd.callback(interaction)

    interaction.response.send_message.assert_awaited_once()


async def test_refresh_clears_cache():
    from familylink_server.bot.commands.usage import make_refresh_command
    svc = AsyncMock()
    svc._members_cache = object()
    svc._usage_cache = {'uid-1': object()}
    cmd = make_refresh_command(svc)

    interaction = _make_interaction(['Parent'])
    await cmd.callback(interaction)

    assert svc._members_cache is None
    assert svc._usage_cache == {}
    interaction.response.send_message.assert_awaited_once()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/server/test_bot_commands.py::test_usage_today_calls_service -v
```

Expected: ImportError.

- [ ] **Step 3: Create `src/familylink_server/bot/commands/usage.py`**

```python
"""Discord /usage, /status, and /refresh commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from familylink_server.bot.commands import child_autocomplete, require_discord_role, resolve_child
from familylink_server.bot.embeds import (
    status_embed,
    usage_history_embed,
    usage_today_embed,
)

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService


class UsageGroup(app_commands.Group, name='usage', description='View usage statistics'):
    """Slash command group: /usage today | history."""

    def __init__(self, service: FamilyLinkService, notifier: DiscordNotifier) -> None:
        super().__init__()
        self._svc = service
        self._notifier = notifier

    @app_commands.command(name='today', description="Show today's app usage for a child")
    @app_commands.describe(child='Which child')
    @app_commands.autocomplete(child=child_autocomplete)
    async def today(self, interaction: discord.Interaction, child: str | None = None) -> None:
        """Show today's usage."""
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message('Please specify a child with the `child` parameter.', ephemeral=True)
            return
        child_id, child_name = resolved
        usage = await self._svc.get_apps_and_usage(child_id)
        top_apps = sorted(
            [
                {'title': a.title, 'seconds': getattr(a, 'usage_today_seconds', 0) or 0}
                for a in usage.apps
            ],
            key=lambda x: x['seconds'],
            reverse=True,
        )[:10]
        total = sum(a['seconds'] for a in top_apps)
        embed = usage_today_embed(child_name, top_apps, total)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='history', description='Show daily usage totals for the last N days')
    @app_commands.describe(child='Which child', days='Number of days (default 7)')
    @app_commands.autocomplete(child=child_autocomplete)
    async def history(
        self,
        interaction: discord.Interaction,
        child: str | None = None,
        days: int = 7,
    ) -> None:
        """Show usage history."""
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message('Please specify a child with the `child` parameter.', ephemeral=True)
            return
        child_id, child_name = resolved
        # Usage history is read from DB via FamilyLinkService if available,
        # or falls back to today's snapshot only.
        usage = await self._svc.get_apps_and_usage(child_id)
        import datetime
        today_total = sum(getattr(a, 'usage_today_seconds', 0) or 0 for a in usage.apps)
        daily_totals = [
            {'date': datetime.date.today().isoformat(), 'seconds': today_total}
        ]
        embed = usage_history_embed(child_name, daily_totals, days)
        await interaction.response.send_message(embed=embed, ephemeral=True)


def make_status_command(service: FamilyLinkService) -> app_commands.Command:
    """Factory: return a /status app_commands.Command bound to service."""

    @app_commands.command(name='status', description='Show a dashboard overview of all children and devices')
    async def status(interaction: discord.Interaction) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        members = await service.get_members()
        supervised = [
            m for m in members.members
            if m.member_supervision_info and m.member_supervision_info.is_supervised_member
        ]
        children_data = []
        for child in supervised:
            usage = await service.get_apps_and_usage(child.user_id)
            total = sum(getattr(a, 'usage_today_seconds', 0) or 0 for a in usage.apps)
            children_data.append({
                'name': child.profile.display_name,
                'total_seconds': total,
                'device_count': len(usage.device_info),
            })
        embed = status_embed(children_data)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    return status


def make_refresh_command(service: FamilyLinkService) -> app_commands.Command:
    """Factory: return a /refresh app_commands.Command bound to service."""

    @app_commands.command(name='refresh', description='Invalidate the cache for all children')
    async def refresh(interaction: discord.Interaction) -> None:
        if not require_discord_role(interaction):
            await interaction.response.send_message('Insufficient permissions.', ephemeral=True)
            return
        service._members_cache = None
        service._usage_cache = {}
        await interaction.response.send_message('♻️ Cache cleared — next request will fetch fresh data.', ephemeral=True)

    return refresh
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/server/test_bot_commands.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/bot/commands/usage.py tests/server/test_bot_commands.py
git commit -m "feat: add Discord /usage, /status, /refresh commands"
```

---

## Task 10: Wire notify_change into Existing Routers

**Files:**
- Modify: `src/familylink_server/routers/apps.py`
- Modify: `src/familylink_server/routers/devices.py`
- Create: `tests/server/test_routers_discord.py`

**Interfaces:**
- Consumes: `get_notifier()` from `discord_notifier` module; called after each successful write
- Produces: after every router write (`set_limit`, `block`, `allow`, `lock_device`, `unlock_device`), `DiscordNotifier.notify_change()` is awaited with `source='web UI'`

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_routers_discord.py`:

```python
"""Tests that routers call DiscordNotifier after writes."""

import os
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://localhost/familylink_test')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-32-bytes-exactly!')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'test-client-id')
os.environ.setdefault('GOOGLE_CLIENT_SECRET', 'test-client-secret')
os.environ.setdefault('FAMILYLINK_GOOGLE_EMAIL', 'parent@gmail.com')
os.environ.setdefault('FAMILYLINK_COOKIES_B64', 'dGVzdA==')

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def test_block_app_notifies_discord(monkeypatch):
    """POST /apps/{package}/block should call DiscordNotifier.notify_change."""
    notifier = AsyncMock()
    notifier.notify_change = AsyncMock()

    svc = AsyncMock()
    member = MagicMock()
    member.user_id = 'uid-1'
    member.profile.display_name = 'Emma'
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    with patch('familylink_server.services.discord_notifier.get_notifier', return_value=notifier), \
         patch('familylink_server.routers.apps.get_service', return_value=svc), \
         patch('familylink_server.routers.apps.get_session'):

        from familylink_server.routers.apps import block_app
        request = MagicMock()
        request.app.state = MagicMock()

        # Simulate the call directly (bypasses FastAPI dependency injection)
        from unittest.mock import AsyncMock as AM
        session = AM()
        session.add = MagicMock()
        session.commit = AM()

        await block_app(
            package='com.tiktok',
            request=request,
            child_id='uid-1',
            _email='parent@gmail.com',
            svc=svc,
            session=session,
        )

    notifier.notify_change.assert_awaited_once()
    args = notifier.notify_change.call_args
    assert args.kwargs.get('action') == 'block' or args.args[0] == 'block'
    assert 'web UI' in (args.kwargs.get('source', '') or str(args.args))


async def test_lock_device_notifies_discord(monkeypatch):
    """POST /devices/{device_id}/lock should call DiscordNotifier.notify_change."""
    notifier = AsyncMock()
    notifier.notify_change = AsyncMock()

    svc = AsyncMock()
    member = MagicMock()
    member.user_id = 'uid-1'
    member.profile.display_name = 'Emma'
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    with patch('familylink_server.services.discord_notifier.get_notifier', return_value=notifier), \
         patch('familylink_server.routers.devices.get_service', return_value=svc), \
         patch('familylink_server.routers.devices.get_session'):

        from familylink_server.routers.devices import lock_device
        request = MagicMock()
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        await lock_device(
            device_id='d-1',
            request=request,
            child_id='uid-1',
            _email='parent@gmail.com',
            svc=svc,
            session=session,
        )

    notifier.notify_change.assert_awaited_once()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/server/test_routers_discord.py -v
```

Expected: both tests FAIL (`notify_change` not called).

- [ ] **Step 3: Modify `src/familylink_server/routers/apps.py`**

Add the `notify_change` call after each write. Import `get_notifier` at the top:

```python
from familylink_server.services.discord_notifier import get_notifier
```

Then in `set_limit`, after `await svc.set_app_limit(...)` and before the `session.add(...)`:

```python
    await svc.set_app_limit(package, minutes, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        members = await svc.get_members()
        child_name = next(
            (m.profile.display_name for m in members.members if m.user_id == child_id),
            child_id,
        )
        await notifier.notify_change('set_limit', child_name, f'{package} ({minutes} min)', 'web UI')
    session.add(...)
```

Apply the same pattern to `block_app` (action `'block'`) and `allow_app` (action `'always_allow'`). The full modified `apps.py`:

```python
"""Router for the /apps HTML page and HTMX limit/block/allow endpoints."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import AuditLog, get_session
from familylink_server.services.discord_notifier import get_notifier
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=['apps'])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / 'templates'))


def _app_state(app) -> dict:
    sup = app.supervision_setting
    if sup.hidden:
        state, state_label = 'blocked', 'Blocked'
    elif sup.usage_limit:
        state, state_label = (
            'limited',
            f'Limited {sup.usage_limit.daily_usage_limit_mins} min',
        )
    elif sup.always_allowed_app_info:
        state, state_label = 'allowed', 'Always allowed'
    else:
        state, state_label = 'unmanaged', 'Unmanaged'
    return {
        'package_name': app.package_name,
        'title': app.title,
        'state': state,
        'state_label': state_label,
        'limit_mins': sup.usage_limit.daily_usage_limit_mins if sup.usage_limit else None,
    }


async def _child_name(svc: FamilyLinkService, child_id: str) -> str:
    members = await svc.get_members()
    return next(
        (m.profile.display_name for m in members.members if m.user_id == child_id),
        child_id,
    )


@router.get('/apps', response_class=HTMLResponse)
async def apps_page(
    request: Request,
    filter: str = 'all',
    child: str = '',
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Render the apps page with a per-child tab strip and inline edit controls."""
    members = await svc.get_members()
    supervised = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    children = [
        {'user_id': m.user_id, 'display_name': m.profile.display_name}
        for m in supervised
    ]

    child_ids = {c['user_id'] for c in children}
    active_child_id = (
        child if child in child_ids else (children[0]['user_id'] if children else '')
    )

    apps = []
    if active_child_id:
        usage = await svc.get_apps_and_usage(active_child_id)
        apps = [
            dict(_app_state(a), child_id=active_child_id)
            for a in sorted(usage.apps, key=lambda x: x.title.lower())
        ]
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
        },
    )


@router.post('/apps/{package}/limit', response_class=HTMLResponse)
async def set_limit(
    package: str,
    request: Request,
    child_id: str = Form(...),
    minutes: int = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Set a daily usage limit for an app and return the updated row partial."""
    await svc.set_app_limit(package, minutes, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        name = await _child_name(svc, child_id)
        await notifier.notify_change('set_limit', name, f'{package} ({minutes} min)', 'web UI')
    session.add(AuditLog(child_id=child_id, action='set_limit', target=package, new_value=str(minutes), occurred_at=datetime.now(UTC)))
    await session.commit()
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'limited',
        'state_label': f'Limited {minutes} min',
        'limit_mins': minutes,
        'child_id': child_id,
    }
    return templates.TemplateResponse(request, 'partials/app_row.html', {'app': app_data})


@router.post('/apps/{package}/block', response_class=HTMLResponse)
async def block_app(
    package: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Block an app and return the updated row partial."""
    await svc.block_app(package, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        name = await _child_name(svc, child_id)
        await notifier.notify_change('block', name, package, 'web UI')
    session.add(AuditLog(child_id=child_id, action='block', target=package, occurred_at=datetime.now(UTC)))
    await session.commit()
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'blocked',
        'state_label': 'Blocked',
        'limit_mins': None,
        'child_id': child_id,
    }
    return templates.TemplateResponse(request, 'partials/app_row.html', {'app': app_data})


@router.post('/apps/{package}/allow', response_class=HTMLResponse)
async def allow_app(
    package: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Always-allow an app and return the updated row partial."""
    await svc.always_allow_app(package, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        name = await _child_name(svc, child_id)
        await notifier.notify_change('always_allow', name, package, 'web UI')
    session.add(AuditLog(child_id=child_id, action='always_allow', target=package, occurred_at=datetime.now(UTC)))
    await session.commit()
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'allowed',
        'state_label': 'Always allowed',
        'limit_mins': None,
        'child_id': child_id,
    }
    return templates.TemplateResponse(request, 'partials/app_row.html', {'app': app_data})
```

- [ ] **Step 4: Modify `src/familylink_server/routers/devices.py`**

Add `from familylink_server.services.discord_notifier import get_notifier` and a `_child_name` helper (same as in apps.py), then add `notify_change` calls in `lock_device` and `unlock_device`. The full modified `devices.py`:

```python
"""Router for the /devices HTML page and HTMX lock/unlock endpoints."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import AuditLog, get_session
from familylink_server.services.discord_notifier import get_notifier
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=['devices'])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / 'templates'))


async def _child_name(svc: FamilyLinkService, child_id: str) -> str:
    members = await svc.get_members()
    return next(
        (m.profile.display_name for m in members.members if m.user_id == child_id),
        child_id,
    )


@router.get('/devices', response_class=HTMLResponse)
async def devices_page(
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Render the devices page listing all supervised devices."""
    members = await svc.get_members()
    children = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    devices = []
    for child in children:
        usage = await svc.get_apps_and_usage(child.user_id)
        for d in usage.device_info:
            devices.append(
                {
                    'device_id': d.device_id,
                    'child_id': child.user_id,
                    'friendly_name': d.display_info.friendly_name,
                    'model': getattr(d.display_info, 'model', None),
                    'is_locked': False,
                }
            )
    return templates.TemplateResponse(request, 'devices.html', {'devices': devices})


@router.post('/devices/{device_id}/lock', response_class=HTMLResponse)
async def lock_device(
    device_id: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Lock a device and return the updated device card partial."""
    await svc.lock_device(device_id, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        name = await _child_name(svc, child_id)
        await notifier.notify_change('lock_device', name, device_id, 'web UI')
    session.add(AuditLog(child_id=child_id, action='lock_device', target=device_id, occurred_at=datetime.now(UTC)))
    await session.commit()
    return templates.TemplateResponse(
        request,
        'partials/device_card.html',
        {
            'device': {
                'device_id': device_id,
                'child_id': child_id,
                'friendly_name': None,
                'is_locked': True,
            },
        },
    )


@router.post('/devices/{device_id}/unlock', response_class=HTMLResponse)
async def unlock_device(
    device_id: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Unlock a device and return the updated device card partial."""
    await svc.unlock_device(device_id, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        name = await _child_name(svc, child_id)
        await notifier.notify_change('unlock_device', name, device_id, 'web UI')
    session.add(AuditLog(child_id=child_id, action='unlock_device', target=device_id, occurred_at=datetime.now(UTC)))
    await session.commit()
    return templates.TemplateResponse(
        request,
        'partials/device_card.html',
        {
            'device': {
                'device_id': device_id,
                'child_id': child_id,
                'friendly_name': None,
                'is_locked': False,
            },
        },
    )
```

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/server/test_routers_discord.py tests/server/ -v
```

Expected: all tests PASS, including pre-existing router tests.

- [ ] **Step 6: Run linter**

```bash
ruff check src tests && ruff format --check src tests
```

Fix any issues, then:

```bash
ruff check --fix src tests && ruff format src tests
```

- [ ] **Step 7: Commit**

```bash
git add src/familylink_server/routers/apps.py src/familylink_server/routers/devices.py \
        tests/server/test_routers_discord.py
git commit -m "feat: wire DiscordNotifier into apps and devices routers"
```

---

## Final Verification

- [ ] **Run the full test suite**

```bash
python -m pytest -v
```

Expected: all tests PASS, zero failures.

- [ ] **Run lint and format check**

```bash
ruff check src tests && ruff format --check src tests
```

Expected: no errors.

- [ ] **Verify bot package is importable without Discord vars**

```bash
python -c "from familylink_server.main import app; print('OK')"
```

Expected: `OK` — no crash even though `DISCORD_BOT_TOKEN` is not set.

- [ ] **Final commit if needed**

```bash
git add -u
git commit -m "chore: final cleanup and linting for Discord bot integration"
```
