# Linux Machine Control — Design Spec

**Date:** 2026-06-25
**Status:** Approved

## Overview

Extend `familylink_server` to manage screen time on Linux machines. The server polls each registered machine over SSH every 60 s, accumulates active session time, and enforces a two-stage limit: a soft screen lock when the daily allowance is exhausted, followed by a hard poweroff after a configurable grace period. Machines are registered and configured through the existing web UI.

## Architecture

A new `linux_machines` subsystem lives alongside the Android/Family Link subsystem inside `familylink_server`. No agent is installed on the Linux machines — the server initiates all SSH connections.

```
familylink_server/
  routers/linux_machines.py           CRUD + manual lock/poweroff endpoints
  services/linux_ssh.py               SSH helpers: check_session, lock, poweroff
  services/linux_poller.py            asyncio background task (the poll loop)
  templates/linux_machines.html       full page
  templates/partials/linux_machine_card.html   HTMX swap target
```

The poller task is created once in `lifespan` alongside the Discord bot task, following the same cancellation pattern.

## Data Model

### `linux_machines`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `child_id` | str(64) | matches Family Link child `user_id` |
| `friendly_name` | str(256) | |
| `hostname` | str(256) | IP or DNS name |
| `ssh_port` | int | default 22 |
| `ssh_user` | str(64) | |
| `ssh_private_key` | text | PEM key, plaintext for POC |
| `daily_limit_mins` | int NULL | NULL = no limit |
| `grace_period_mins` | int | default 5 |
| `enabled` | bool | default true |
| `created_at` | datetime | |

> SSH key encryption at rest (using `settings.SECRET_KEY`) is out of scope for the POC but should be added before production use.

### `linux_usage_snapshots`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `machine_id` | int FK → `linux_machines.id` | |
| `date` | date | |
| `active_seconds` | int | accumulated today |
| `locked_at` | datetime NULL | set when soft lock applied |
| `poweroff_at` | datetime NULL | set when hard poweroff applied |
| `updated_at` | datetime | |

Unique constraint: `(machine_id, date)`.

## SSH Polling & Enforcement Loop (`linux_poller.py`)

Runs as a single asyncio background task. Cycle: every 60 s.

Each cycle iterates all enabled machines concurrently via `asyncio.gather`. Each machine coroutine has a 10 s SSH timeout (via `asyncssh`).

### Session check

```bash
loginctl list-sessions --no-pager
```

A session with `STATE=active` means the user is present. Falls back to `who` if `loginctl` is unavailable.

### Usage accumulation

If the session is active, add 60 s to `linux_usage_snapshots.active_seconds` for today (upsert). Idle/locked time does not accumulate.

### Soft lock

Trigger: `active_seconds >= daily_limit_mins * 60` AND `locked_at IS NULL`.

```bash
loginctl lock-sessions
```

Sets `locked_at = now()`.

### Hard poweroff

Trigger: `locked_at IS NOT NULL` AND `now() - locked_at >= grace_period_mins * 60`.

```bash
systemctl poweroff
```

Sets `poweroff_at = now()`. The poller skips this machine for the rest of the calendar day.

### Manual overrides

Web UI endpoints call the same SSH helpers in `linux_ssh.py` directly, bypassing the timer. This allows immediate lock or poweroff from the UI.

## Web UI

### `/linux-machines` page

Lists all registered machines as cards. Each card shows:
- Friendly name, hostname, associated child
- Today's usage progress bar (active minutes / limit)
- Status badge: `Active` / `Idle` / `Locked` / `Powered off`
- Action buttons: **Lock now**, **Power off now** (HTMX POST, returns updated card partial)
- Edit / Delete links

### Add / Edit form

Fields:
- Friendly name
- Child (dropdown populated from Family Link members)
- Hostname, SSH port (default 22), SSH user
- SSH private key (PEM textarea)
- Daily limit in minutes (optional — leave blank for no limit)
- Grace period in minutes (default 5)
- Enabled toggle

### HTMX pattern

Follows the existing device card pattern:

- `POST /linux-machines/{id}/lock` → returns `partials/linux_machine_card.html`
- `POST /linux-machines/{id}/poweroff` → returns `partials/linux_machine_card.html`
- `POST /linux-machines` (create) → redirects to list
- `POST /linux-machines/{id}/edit` → redirects to list
- `DELETE /linux-machines/{id}` → removes card via HTMX `hx-swap="delete"`

### Navigation

Add a **Linux Machines** link to the existing top nav alongside Devices, Apps, Members.

## Dependencies

- `asyncssh` — async SSH client; add to `pyproject.toml` and `requirements.txt`
- New Alembic migration for the two tables

## Out of Scope (POC)

- SSH key encryption at rest
- Per-child aggregate view across Android + Linux usage
- Discord notifications for Linux lock/poweroff events
- Timezone-aware scheduling (e.g. "lock at 21:00 regardless of usage")
