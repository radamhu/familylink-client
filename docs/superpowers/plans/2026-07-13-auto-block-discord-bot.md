# Discord Slash Commands for Auto-Block & Bonus — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/apps auto-block` and `/apps bonus` Discord slash subcommands so a parent can toggle auto-block opt-in and grant bonus minutes without opening the web UI — the follow-up to the item marked "web UI only for now" in `docs/superpowers/specs/2026-07-13-auto-block-overused-apps-design.md` (Out of Scope).

**Architecture:** Two new subcommands on the existing `AppsGroup` (`src/familylink_server/bot/commands/apps.py`), mirroring the two new HTMX endpoints already shipped in `src/familylink_server/routers/apps.py` (`set_auto_block`, `grant_bonus`). Each subcommand talks to the DB directly via a `make_session` factory — the same pattern `LinuxGroup` already uses for its `/linux bonus` command — rather than going through the HTTP router. Business logic (get-or-create `AppConfig`, bonus stacking rule, unblock-on-bonus) is duplicated in the bot command rather than extracted into a shared service function, matching the existing precedent: `LinuxGroup.bonus` already duplicates `routers/linux_machines.py`'s bonus logic instead of sharing it.

**Tech Stack:** discord.py `app_commands`, SQLAlchemy async session, existing `FamilyLinkService`.

## Global Constraints

- Slash commands are guild-scoped (`self.guild_id`) and gated by `require_discord_role` (checks `settings.discord_allowed_role`) — every new command callback must call it first, exactly like every existing subcommand.
- Bonus values are restricted to 15/30/60 minutes via `app_commands.Choice`, same set as `/linux bonus` and the web UI's `VALID_BONUS_MINUTES`.
- No new DB columns or migrations — `auto_block_enabled`, `auto_blocked_at`, `bonus_mins`, `bonus_date` already exist on `AppConfig` (`src/familylink_server/db/models.py:22`).
- Auto-block toggle and bonus grants write to `AuditLog` only — they do **not** call `DiscordNotifier.notify_change`, matching `routers/apps.py`'s `set_auto_block`/`grant_bonus` (only `set_limit`/`block_app`/`allow_app` notify; this is the existing convention, not a gap to fix here).
- All replies are plain ephemeral text messages (`ephemeral=True`), no embeds — matches every existing `/apps` and `/linux bonus` reply.
- `AppConfig` lookups always key on `(child_id, package_name)`, get-or-create semantics, same as `_get_or_create_app_config` in `routers/apps.py`.

---

### Task 1: Wire a DB session into `AppsGroup` + add `/apps auto-block`

**Files:**
- Modify: `src/familylink_server/bot/commands/apps.py`
- Modify: `src/familylink_server/bot/client.py:151` (pass `make_session` into `AppsGroup`)
- Modify: `tests/server/test_bot_commands.py` (update 4 existing `AppsGroup(svc, notifier)` call sites)
- Test: `tests/server/test_bot_commands.py`

**Interfaces:**
- Consumes: `familylink_server.db.AppConfig`, `familylink_server.db.AuditLog` (same import path `routers/apps.py` uses); `familylink_server.bot.commands.require_discord_role`, `resolve_child`, `child_autocomplete`.
- Produces: `AppsGroup.__init__(self, service, notifier, *, make_session)` — `make_session: Callable[[], AbstractAsyncContextManager[AsyncSession]]`, required keyword-only, no default (matches `LinuxGroup`). `AppsGroup.auto_block` command callback, signature `(interaction, package: str, enabled: bool, child: str | None = None)`.

- [ ] **Step 1: Update `AppsGroup.__init__` to accept `make_session`**

In `src/familylink_server/bot/commands/apps.py`, update imports and constructor:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from familylink_server.bot.commands import (
    child_autocomplete,
    require_discord_role,
    resolve_child,
)
from familylink_server.bot.embeds import apps_list_embed
from familylink_server.db import AppConfig, AuditLog

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime as dt_datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

_PAGE_SIZE = 10


class AppsGroup(app_commands.Group, name='apps', description='Manage supervised apps'):
    """Slash command group: /apps list | limit | block | allow | auto-block | bonus."""

    def __init__(
        self,
        service: FamilyLinkService,
        notifier: DiscordNotifier,
        *,
        make_session: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    ) -> None:
        super().__init__()
        self._svc = service
        self._notifier = notifier
        self._make_session = make_session
```

Leave `list`, `limit`, `block`, `allow` methods unchanged.

- [ ] **Step 2: Add a shared get-or-create helper at module scope**

Add below the imports, above the class (same logic as `routers/apps.py::_get_or_create_app_config`, needed by both new subcommands):

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

- [ ] **Step 3: Add the `auto-block` subcommand**

Append as a new method on `AppsGroup`, after `allow`:

```python
    @app_commands.command(
        name='auto-block',
        description="Toggle auto-block-on-overuse for an app that has a Google-side limit",
    )
    @app_commands.describe(
        package='App package name (e.g. com.zhiliaoapp.musically)',
        enabled='Turn auto-block on or off',
        child='Which child',
    )
    @app_commands.autocomplete(child=child_autocomplete)
    async def auto_block(
        self,
        interaction: discord.Interaction,
        package: str,
        enabled: bool,
        child: str | None = None,
    ) -> None:
        """Toggle the auto-block-on-overuse opt-in for an app."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                'Insufficient permissions.', ephemeral=True
            )
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message(
                'Please specify a child with the `child` parameter.', ephemeral=True
            )
            return
        child_id, child_name = resolved

        usage = await self._svc.get_apps_and_usage(child_id)
        app_match = next((a for a in usage.apps if a.package_name == package), None)
        if enabled and (
            app_match is None or not app_match.supervision_setting.usage_limit
        ):
            await interaction.response.send_message(
                f'`{package}` has no active Google-side daily limit for {child_name} — '
                'auto-block needs a limit to enforce against.',
                ephemeral=True,
            )
            return

        async with self._make_session() as session:
            config = await _get_or_create_app_config(session, child_id, package)
            config.auto_block_enabled = enabled
            session.add(
                AuditLog(
                    child_id=child_id,
                    action='auto_block_toggle',
                    target=package,
                    new_value=str(enabled),
                    occurred_at=__import__('datetime').datetime.now(
                        __import__('datetime').UTC
                    ),
                )
            )
            await session.commit()

        state = 'enabled' if enabled else 'disabled'
        await interaction.response.send_message(
            f'\N{GEAR}️ Auto-block **{state}** for `{package}` ({child_name}).',
            ephemeral=True,
        )
```

Replace the inline `__import__('datetime')` calls with a proper top-of-file import — add `from datetime import UTC, datetime` to the imports in Step 1 and use `datetime.now(UTC)` directly. (Written inline above only to show the exact call; the real edit uses the clean import.)

- [ ] **Step 4: Wire `make_session` into the bot client**

In `src/familylink_server/bot/client.py`, update the `AppsGroup` construction at line 151:

```python
            self.tree.add_command(
                AppsGroup(self.service, self.notifier, make_session=self._make_session),
                guild=guild,
            )
```

- [ ] **Step 5: Fix existing tests broken by the new required kwarg**

In `tests/server/test_bot_commands.py`, update all 4 call sites (lines 109, 131, 153, 173) from:

```python
    group = AppsGroup(svc, notifier)
```

to:

```python
    group = AppsGroup(svc, notifier, make_session=MagicMock())
```

Add `from unittest.mock import MagicMock` to the top of the file if not already imported (it already is, per the `_make_interaction` helper).

- [ ] **Step 6: Write the failing tests for `/apps auto-block`**

Append to `tests/server/test_bot_commands.py`:

```python
def _make_session_ctx(config=None):
    from unittest.mock import AsyncMock

    mock_session = AsyncMock()
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = config
    mock_exec_result.scalar_one.return_value = config
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx, mock_session


async def test_apps_auto_block_enables_when_app_has_limit():
    """'/apps auto-block' sets auto_block_enabled=True when the app has a Google limit."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    app = MagicMock()
    app.package_name = 'com.tiktok'
    app.supervision_setting.usage_limit = MagicMock(daily_usage_limit_mins=60)
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app])

    config = MagicMock()
    config.auto_block_enabled = False
    mock_ctx, mock_session = _make_session_ctx(config=config)
    make_session = MagicMock(return_value=mock_ctx)

    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.auto_block.callback(
        group, interaction, package='com.tiktok', enabled=True, child='uid-1'
    )

    assert config.auto_block_enabled is True
    mock_session.commit.assert_awaited_once()
    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.call_args[0][0]
    assert 'enabled' in msg.lower()
    assert 'com.tiktok' in msg


async def test_apps_auto_block_rejects_app_without_limit():
    """'/apps auto-block' refuses to enable when the app has no Google-side limit."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    app = MagicMock()
    app.package_name = 'com.tiktok'
    app.supervision_setting.usage_limit = None
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app])

    make_session = MagicMock()
    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.auto_block.callback(
        group, interaction, package='com.tiktok', enabled=True, child='uid-1'
    )

    make_session.assert_not_called()
    msg = interaction.response.send_message.call_args[0][0]
    assert 'no active' in msg.lower()


async def test_apps_auto_block_requires_role():
    """'/apps auto-block' replies with permission error without the Discord role."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()
    make_session = MagicMock()
    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction([])

    await group.auto_block.callback(
        group, interaction, package='com.tiktok', enabled=True, child='uid-1'
    )

    msg = interaction.response.send_message.call_args[0][0]
    assert 'permission' in msg.lower() or 'insufficient' in msg.lower()
```

- [ ] **Step 7: Run the tests to verify they fail**

Run: `python -m pytest tests/server/test_bot_commands.py -v`
Expected: `FAIL` — `AttributeError: 'AppsGroup' object has no attribute 'auto_block'` (or `TypeError` on the constructor) until Steps 1–4 are applied.

- [ ] **Step 8: Apply Steps 1–4, then run tests again**

Run: `python -m pytest tests/server/test_bot_commands.py -v`
Expected: `PASS` — all tests including the 3 new ones and the 4 pre-existing ones.

- [ ] **Step 9: Commit**

```bash
git add src/familylink_server/bot/commands/apps.py src/familylink_server/bot/client.py tests/server/test_bot_commands.py
git commit -m "feat: add /apps auto-block Discord slash command"
```

---

### Task 2: Add `/apps bonus`

**Files:**
- Modify: `src/familylink_server/bot/commands/apps.py`
- Test: `tests/server/test_bot_commands.py`

**Interfaces:**
- Consumes: `AppsGroup._make_session`, `AppsGroup._svc`, `_get_or_create_app_config` (from Task 1, same module).
- Produces: `AppsGroup.bonus` command callback, signature `(interaction, package: str, minutes: int, child: str | None = None)`.

- [ ] **Step 1: Add the `bonus` subcommand**

Append to `AppsGroup` in `src/familylink_server/bot/commands/apps.py`, after `auto_block`:

```python
    @app_commands.command(
        name='bonus', description='Grant bonus minutes to an auto-blocked app'
    )
    @app_commands.describe(
        package='App package name', minutes='Extra minutes to grant', child='Which child'
    )
    @app_commands.choices(
        minutes=[
            app_commands.Choice(name='+15 min', value=15),
            app_commands.Choice(name='+30 min', value=30),
            app_commands.Choice(name='+60 min', value=60),
        ]
    )
    @app_commands.autocomplete(child=child_autocomplete)
    async def bonus(
        self,
        interaction: discord.Interaction,
        package: str,
        minutes: int,
        child: str | None = None,
    ) -> None:
        """Grant bonus minutes to an app, unblocking it immediately if auto-blocked."""
        if not require_discord_role(interaction):
            await interaction.response.send_message(
                'Insufficient permissions.', ephemeral=True
            )
            return
        resolved = await resolve_child(self._svc, child)
        if resolved is None:
            await interaction.response.send_message(
                'Please specify a child with the `child` parameter.', ephemeral=True
            )
            return
        child_id, child_name = resolved

        async with self._make_session() as session:
            config = await _get_or_create_app_config(session, child_id, package)
            today = datetime.now(UTC).date()
            if config.bonus_date != today:
                config.bonus_mins = minutes
                config.bonus_date = today
            else:
                config.bonus_mins += minutes

            unblocked = False
            if config.auto_blocked_at is not None:
                usage = await self._svc.get_apps_and_usage(child_id)
                app_match = next(
                    (a for a in usage.apps if a.package_name == package), None
                )
                base_limit = (
                    app_match.supervision_setting.usage_limit.daily_usage_limit_mins
                    if app_match is not None and app_match.supervision_setting.usage_limit
                    else 0
                )
                await self._svc.set_app_limit(
                    package, base_limit + config.bonus_mins, child_id=child_id
                )
                config.auto_blocked_at = None
                unblocked = True

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
            bonus_total = config.bonus_mins

        msg = (
            f'⏰ +{minutes} min bonus granted for `{package}` ({child_name}) '
            f'— {bonus_total} min bonus today.'
        )
        if unblocked:
            msg += ' App unblocked.'
        await interaction.response.send_message(msg, ephemeral=True)
```

Add `from datetime import UTC, datetime` to the top-of-file imports (same import Task 1 Step 3 already introduces — if Task 1 is done first, this is a no-op check, not a duplicate import).

- [ ] **Step 2: Write the failing tests**

Append to `tests/server/test_bot_commands.py`:

```python
async def test_apps_bonus_stacks_same_day():
    """'/apps bonus' adds to existing same-day bonus_mins."""
    from familylink_server.bot.commands.apps import AppsGroup

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    from datetime import UTC, datetime

    config = MagicMock()
    config.bonus_mins = 15
    config.bonus_date = datetime.now(UTC).date()
    config.auto_blocked_at = None
    mock_ctx, mock_session = _make_session_ctx(config=config)
    make_session = MagicMock(return_value=mock_ctx)

    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.bonus.callback(
        group, interaction, package='com.tiktok', minutes=30, child='uid-1'
    )

    assert config.bonus_mins == 45
    svc.set_app_limit.assert_not_called()
    msg = interaction.response.send_message.call_args[0][0]
    assert '+30' in msg
    assert '45 min bonus today' in msg


async def test_apps_bonus_resets_on_new_day():
    """'/apps bonus' resets bonus_mins when bonus_date is not today."""
    from familylink_server.bot.commands.apps import AppsGroup
    from datetime import date

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    config = MagicMock()
    config.bonus_mins = 999
    config.bonus_date = date(2000, 1, 1)
    config.auto_blocked_at = None
    mock_ctx, mock_session = _make_session_ctx(config=config)
    make_session = MagicMock(return_value=mock_ctx)

    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.bonus.callback(
        group, interaction, package='com.tiktok', minutes=15, child='uid-1'
    )

    assert config.bonus_mins == 15


async def test_apps_bonus_unblocks_when_auto_blocked():
    """'/apps bonus' calls set_app_limit and clears auto_blocked_at when currently blocked."""
    from familylink_server.bot.commands.apps import AppsGroup
    from datetime import UTC, datetime

    svc = AsyncMock()
    notifier = AsyncMock()

    m = MagicMock()
    m.user_id = 'uid-1'
    m.profile.display_name = 'Emma'
    m.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[m])

    app = MagicMock()
    app.package_name = 'com.tiktok'
    app.supervision_setting.usage_limit = MagicMock(daily_usage_limit_mins=60)
    svc.get_apps_and_usage.return_value = MagicMock(apps=[app])

    config = MagicMock()
    config.bonus_mins = 0
    config.bonus_date = datetime.now(UTC).date()
    config.auto_blocked_at = datetime.now(UTC)
    mock_ctx, mock_session = _make_session_ctx(config=config)
    make_session = MagicMock(return_value=mock_ctx)

    group = AppsGroup(svc, notifier, make_session=make_session)
    interaction = _make_interaction(['Parent'])

    await group.bonus.callback(
        group, interaction, package='com.tiktok', minutes=30, child='uid-1'
    )

    svc.set_app_limit.assert_awaited_once_with('com.tiktok', 90, child_id='uid-1')
    assert config.auto_blocked_at is None
    msg = interaction.response.send_message.call_args[0][0]
    assert 'unblocked' in msg.lower()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/server/test_bot_commands.py -v -k bonus`
Expected: `FAIL` — `AttributeError: 'AppsGroup' object has no attribute 'bonus'`.

- [ ] **Step 4: Apply Step 1, then run tests again**

Run: `python -m pytest tests/server/test_bot_commands.py -v`
Expected: `PASS` — all tests in the file, including Task 1's.

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/bot/commands/apps.py tests/server/test_bot_commands.py
git commit -m "feat: add /apps bonus Discord slash command"
```

---

### Task 3: Update `client.py`'s `setup_hook` docstring/registration test coverage

**Files:**
- Test: `tests/server/test_bot_commands.py` or wherever bot client wiring is covered (check for an existing `test_client.py`-style file under `tests/server/` first; if none exists for `client.py`, skip this task — registration is already exercised indirectly by Task 1 Step 4's manual edit, and `on_ready`/`setup_hook` aren't otherwise unit tested per the existing test suite).

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new — this task is a coverage check, not a code change.

- [ ] **Step 1: Confirm no test asserts the exact `AppsGroup(...)` call signature in `setup_hook`**

Run: `grep -rn "AppsGroup(self.service" tests/`
Expected: no matches (the constructor call lives only in `client.py`, not asserted in tests). If a match is found, update that assertion to include `make_session=`.

- [ ] **Step 2: No commit needed if Step 1 found nothing to change.**

---

## Self-Review Notes

**Spec coverage:** The out-of-scope line reads "Bot/Discord slash command to toggle auto-block or grant bonus (web UI only for now)." Task 1 covers "toggle auto-block," Task 2 covers "grant bonus." Both mirror the already-shipped `routers/apps.py` endpoints (`set_auto_block`, `grant_bonus`) field-for-field, including the same `AuditLog` actions (`auto_block_toggle`, `bonus_app`) and the same bonus-stacking-vs-reset rule.

**Deliberate deviations from the web UI, and why:**
- The `auto-block` subcommand rejects enabling on an app with no live Google usage limit (`get_apps_and_usage` check) — the web UI enforces this by only rendering the checkbox for `state == 'limited'` rows (`app_row.html`), which a slash command has no equivalent of, so the check moves server-side into the command itself.
- `bonus` reports the running `bonus_total` in its reply — the HTMX partial shows this via the re-rendered row's `state_label` (`f'Limited {base_limit} min (+{bonus_mins} bonus today)'`); a slash command has no row to re-render, so the total is stated directly in the ephemeral reply text instead.

**Not duplicated further:** No new service-layer abstraction was introduced to share logic between `routers/apps.py` and `bot/commands/apps.py` — this matches the existing precedent (`LinuxGroup.bonus` vs. `routers/linux_machines.py`'s bonus endpoint are already two independent implementations in this codebase).
