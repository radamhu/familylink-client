# Linux Bonus Time & Dashboard Integration — Design Spec

**Date:** 2026-06-25
**Status:** Pending approval

## Overview

Allow a parent to grant extra screen time to a Linux machine beyond its daily limit. Bonus time is per-day: it extends today's effective limit and, if the machine is already soft-locked, automatically unlocks it via SSH. No new tables are required.

## Data Model

Add one column to `linux_usage_snapshots`:

| Column | Type | Notes |
|---|---|---|
| `bonus_mins` | int NOT NULL DEFAULT 0 | Cumulative bonus minutes granted today |

Alembic migration: `003_bonus_mins.py`.

The effective daily cap throughout the system is `daily_limit_mins + bonus_mins`. When `daily_limit_mins` is NULL (no limit configured), bonus time has no effect — the machine is never locked.

## Enforcement Logic (`linux_poller.py`)

One change to the lock trigger:

```python
effective_limit = machine.daily_limit_mins + snapshot.bonus_mins
# was: machine.daily_limit_mins * 60
if snapshot.active_seconds >= effective_limit * 60 and snapshot.locked_at is None:
    ...  # soft lock
```

Everything else in the poller is unchanged: grace period countdown, poweroff, early-exit when `poweroff_at` is set.

## Bonus Endpoint (`routers/linux_machines.py`)

`POST /linux-machines/{id}/bonus` — form field `minutes: int` (accepted values: 15, 30, 60).

Steps:
1. Get or create today's `LinuxUsageSnapshot`.
2. Add `minutes` to `snapshot.bonus_mins`.
3. If `snapshot.locked_at is not None` and `snapshot.poweroff_at is None`: SSH `loginctl unlock-sessions`, reset `snapshot.locked_at = None`.
4. Write `AuditLog(action="bonus_linux", new_value=str(minutes))`.
5. Return the updated `partials/linux_machine_card.html` partial (HTMX `outerHTML` swap).

If the machine is already powered off: bonus is saved to the DB but no SSH is attempted; the card stays in `powered_off` state.

## Web UI (`partials/linux_machine_card.html`)

Three new buttons in the card footer, shown only when `status != 'powered_off'`:

```
[+15 min]  [+30 min]  [+60 min]
```

Each is a small inline `hx-post` form targeting the card's `outerHTML`, identical pattern to Lock / Power off.

The progress bar uses `effective_limit_mins` (= `daily_limit_mins + bonus_mins`) rather than the raw `daily_limit_mins`, so the bar reflects the extended cap. The router passes this value as `effective_limit_mins` in the template context.

## Template Context Changes

`_machine_context()` gains one new key:

| Key | Value |
|---|---|
| `effective_limit_mins` | `daily_limit_mins + bonus_mins` if limit set, else `None` |
| `bonus_mins` | raw bonus granted today (for display if desired) |

The card partial replaces `machine.daily_limit_mins` with `effective_limit_mins` in the progress bar `max` attribute.

## Files Changed

| Action | Path |
|---|---|
| Create | `alembic/versions/003_bonus_mins.py` |
| Modify | `src/familylink_server/db/models.py` — add `bonus_mins` to `LinuxUsageSnapshot` |
| Modify | `src/familylink_server/services/linux_poller.py` — use `effective_limit` |
| Modify | `src/familylink_server/services/linux_ssh.py` — add `unlock_session()` helper |
| Modify | `src/familylink_server/routers/linux_machines.py` — add `/bonus` endpoint, update `_machine_context()` |
| Modify | `src/familylink_server/templates/partials/linux_machine_card.html` — add bonus buttons, fix progress bar |
| Modify | `tests/server/test_linux_poller.py` — update snapshot fixture, add bonus threshold test |
| Modify | `tests/server/test_linux_ssh.py` — add `unlock_session` test |
| Modify | `tests/server/test_routers_linux_machines.py` — add bonus endpoint tests |

## Dashboard Integration (`routers/dashboard.py`)

The dashboard currently shows per-child Android usage (total seconds, top-5 apps, devices). It will gain a **Linux Machines** subsection for each child who has at least one registered machine.

### Router changes

The dashboard handler gains a `session: AsyncSession = Depends(get_session)` parameter. For each child in `child_data`, the handler:

1. Queries all enabled `LinuxMachine` rows where `child_id = child.user_id`.
2. For each machine, fetches today's `LinuxUsageSnapshot` (or treats as zero if absent).
3. Computes `effective_limit_mins = daily_limit_mins + bonus_mins` (None if no limit).
4. Builds a `linux_machines` list in the child dict:

```python
{
    "friendly_name": machine.friendly_name,
    "active_mins": snapshot.active_seconds // 60,
    "effective_limit_mins": effective_limit_mins,
    "status": "powered_off" | "locked" | "active",
}
```

The logic is self-contained in `dashboard.py` — no import from the linux_machines router.

### Template changes (`dashboard.html`)

After the **Devices** subsection for each child, add a **Linux Machines** subsection (only rendered when `child.linux_machines` is non-empty):

```
Linux Machines
  Gaming PC    [====-------]  34 / 90 min  [active]
  Homework PC  [no limit]                  [active]
```

Each row shows:
- Friendly name
- Progress bar (`active_mins / effective_limit_mins`) — omitted when no limit
- Status badge (active / locked / powered off) using the same colour scheme as the card partial

No action buttons on the dashboard — it is read-only. The dashboard auto-refreshes every 5 minutes (existing `hx-get` trigger already in place), so Linux usage stays current without extra wiring.

### Files added for dashboard integration

| Action | Path |
|---|---|
| Modify | `src/familylink_server/routers/dashboard.py` — add DB session, per-child Linux query |
| Modify | `src/familylink_server/templates/dashboard.html` — add Linux Machines subsection |
| Modify | `tests/server/test_dashboard.py` — add test for Linux machines appearing in response |

## Discord Bot Integration

### Architecture change — DB access for the bot

`FamilyLinkBot.__init__` gains one new parameter:

```python
make_session: Callable[[], AbstractAsyncContextManager[AsyncSession]]
```

This is the same `make_session` factory used by the poller. It is stored as `self._make_session` and passed down to commands that need DB reads/writes. `main.py` passes it when constructing the bot during lifespan.

### A) Read: `/status` and daily summary

Both the `/status` slash command (`make_status_command`) and `_run_daily_summary` gain a per-child Linux query using `self._make_session`:

1. For each supervised child, query all enabled `LinuxMachine` rows for that `child_id`.
2. For each machine, fetch today's `LinuxUsageSnapshot` (zero if absent).
3. Compute `effective_limit_mins = daily_limit_mins + bonus_mins`.
4. Build a list of Linux machine summaries per child.

`status_embed` and `daily_summary_embed` in `bot/embeds.py` each gain an optional `linux_machines: list[dict]` parameter. When non-empty, a **Linux** section is appended to the embed showing each machine as an inline field:

```
Gaming PC     34 / 90 min  🟢 active
Homework PC   no limit     🟢 active
```

Status icons: 🟢 active · 🟠 locked · 🔴 powered off.

### B) `/linux bonus` slash command

New file `bot/commands/linux.py` — `LinuxGroup(app_commands.Group, name="linux")`:

**`/linux bonus machine:<autocomplete> minutes:<choice>`**

- `minutes` choices: 15, 30, 60 (Discord `Choice[int]`).
- `machine` autocomplete: queries all `linux_machines` via `make_session`, returns up to 25 `Choice(name=friendly_name, value=str(machine_id))`.
- Handler steps (same logic as the HTTP `/bonus` endpoint):
  1. Get or create today's `LinuxUsageSnapshot` for the machine.
  2. Add `minutes` to `snapshot.bonus_mins`.
  3. If `locked_at is not None` and `poweroff_at is None`: SSH `loginctl unlock-sessions`, reset `locked_at = None`.
  4. Write `AuditLog(action="bonus_linux", new_value=str(minutes), child_id=machine.child_id, target=machine.friendly_name)`.
  5. Reply ephemeral: `"⏰ +{minutes} min granted for {friendly_name}."` (or `"⏰ +{minutes} min granted and machine unlocked."` if unlock was performed).
- `require_discord_role` guard (same as all other bot commands).

`LinuxGroup` is registered in `bot/client.py` `setup_hook` alongside `AppsGroup`, `DevicesGroup`, `UsageGroup`.

### C) Poller notifications

`poll_machine` and `poller_loop` gain an optional `notifier: DiscordNotifier | None = None` parameter.

On soft lock (after `loginctl lock-sessions` succeeds):
```python
if notifier:
    await notifier.notify_change(
        "lock_linux", machine.child_id, machine.friendly_name, "poller"
    )
```

On hard poweroff (after `systemctl poweroff` succeeds):
```python
if notifier:
    await notifier.notify_change(
        "poweroff_linux", machine.child_id, machine.friendly_name, "poller"
    )
```

`_ACTION_MAP` in `bot/embeds.py` gains two new entries:

```python
"lock_linux":    ("🔒 Linux Machine Locked",      discord.Color.orange()),
"poweroff_linux":("⚡ Linux Machine Powered Off", discord.Color.red()),
"bonus_linux":   ("⏰ Bonus Time Granted",         discord.Color.green()),
```

In `main.py`, the notifier variable is hoisted so it is accessible outside the `if settings.discord_enabled:` block, defaulting to `None`:

```python
notifier: DiscordNotifier | None = None
if settings.discord_enabled:
    notifier = init_notifier(...)
    ...

poller_task = asyncio.create_task(poller_loop(notifier=notifier))
```

## Files Changed (full list)

| Action | Path |
|---|---|
| Create | `alembic/versions/003_bonus_mins.py` |
| Create | `src/familylink_server/bot/commands/linux.py` — LinuxGroup with `/linux bonus` |
| Modify | `src/familylink_server/db/models.py` — add `bonus_mins` to `LinuxUsageSnapshot` |
| Modify | `src/familylink_server/services/linux_poller.py` — effective_limit, optional notifier |
| Modify | `src/familylink_server/services/linux_ssh.py` — add `unlock_session()` helper |
| Modify | `src/familylink_server/routers/linux_machines.py` — add `/bonus` endpoint, update `_machine_context()` |
| Modify | `src/familylink_server/routers/dashboard.py` — add DB session, per-child Linux query |
| Modify | `src/familylink_server/bot/client.py` — accept `make_session`, register LinuxGroup, update status+summary |
| Modify | `src/familylink_server/bot/embeds.py` — extend `_ACTION_MAP`, add linux_machines param to status/summary embeds |
| Modify | `src/familylink_server/main.py` — hoist notifier, pass to poller_loop + FamilyLinkBot |
| Modify | `src/familylink_server/templates/partials/linux_machine_card.html` — add bonus buttons, fix progress bar |
| Modify | `src/familylink_server/templates/dashboard.html` — add Linux Machines subsection |
| Modify | `tests/server/test_linux_poller.py` — update snapshot fixture, bonus threshold, notifier call tests |
| Modify | `tests/server/test_linux_ssh.py` — add `unlock_session` test |
| Modify | `tests/server/test_routers_linux_machines.py` — add bonus endpoint tests |
| Modify | `tests/server/test_dashboard.py` — add Linux machines in dashboard test |
| Create | `tests/server/test_bot_linux.py` — LinuxGroup bonus command tests |

## Out of Scope

- Per-preset configuration (amounts are hardcoded: 15, 30, 60 min)
- Bonus time carried over to the next day (resets with the snapshot at midnight)
- Notification to child that bonus was granted
- Clickable Linux machine rows on the dashboard (read-only view only)
- `/linux status` command (Linux info is already in `/status`)
