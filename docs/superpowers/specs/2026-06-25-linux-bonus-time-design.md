# Linux Bonus Time — Design Spec

**Date:** 2026-06-25
**Status:** Approved

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

## Out of Scope

- Per-preset configuration (amounts are hardcoded: 15, 30, 60 min)
- Bonus time carried over to the next day (resets with the snapshot at midnight)
- Notification to child that bonus was granted
