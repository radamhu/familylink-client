# Family Link Client — Repository Summary

## Overview

**Family Link** is a non-official Python package to interact with [Google Family Link](https://families.google.com/familylink), enabling parents to manage kids' screen time (app limits, blocking, always-allowed). It can be used as a **CLI** (config-driven from CSV) or as a **library** (programmatic API).

---

## Components

| Component | Path | Role |
|-----------|------|------|
| **CLI** | `src/familylink/cli.py` | Entry point; parses CSV config, applies limits via `FamilyLink` client |
| **Client** | `src/familylink/client.py` | HTTP client for Kids Management API; auth (SAPISID/cookies); GET + device write (POST) |
| **Models** | `src/familylink/models.py` | Pydantic models for API responses (apps, usage, members) |
| **Config editor** | `index.html` | Standalone web UI to edit `config.csv` (drag-drop, add/delete rows, save CSV) |

---

## Entry Points

- **CLI**: `familylink` (or `python -m familylink.cli`) → `cli:main`
- **Library**: `from familylink import FamilyLink`

---

## Configuration (CSV)

Config file format (default `config.csv`):

| Column | Description |
|--------|-------------|
| **App** | Exact app name (as in Family Link) |
| **Max Duration** | `H:MM` (e.g. `0:30`, `1:00`) |
| **Days** | `Mon–Fri`, `Sat–Sun`, single day, or empty = all days |
| **Time Ranges** | `HH:MM–HH:MM` (e.g. `09:00–17:00`), optional |

- **Always allowed**: empty duration, days, and time ranges.
- **Limited**: duration + optional days/time windows.
- **Blocked**: app not in config, or not matching current schedule → CLI blocks it.

---

## Auth & Environment (Client)

The client is patched for **Docker / profile-based** use:

- **SAPISID**: `FAMILYLINK_SAPISID`, or `sapisid.txt` / `SAPISID` in profile dir.
- **Cookies**: `FAMILYLINK_COOKIE_FILE` or `--cookie-file`, or `cookies.txt` in profile dir.
- **Browser**: `FAMILYLINK_BROWSER` (`firefox` / `chrome`) for host-only `browser_cookie3` fallback; **`txt`** = cookies from file only (`cookies.txt` or `cookie_file_path`), no browser sync (e.g. Home Assistant).
- **Profile dir**: `FAMILYLINK_PROFILES_DIR`; when `cwd` is under it, local `sapisid.txt` / `cookies.txt` / `authuser.txt` are used. In containers, browser access is disabled; files or env must be provided.

---

## API Surface (Client)

| Method | Purpose |
|--------|---------|
| `get_members()` | List family members (parent/child). Returns `MembersResponse`. |
| `print_usage()` | Prints member names, emails, `user_id` to stdout. |
| `get_apps_and_usage(child_id)` | GET `/people/{child_id}/appsandusage` (raw JSON). |
| `get_time_limit(child_id)` | GET `/people/{child_id}/timeLimit`. |
| `get_applied_time_limits(child_id)` | GET `/people/{child_id}/appliedTimeLimits`. |
| `get_time_limits(account_id?)` | GET applied time limits (today). Uses `_ensure_account_id()` if no `account_id`. |
| `set_time_limits_device(account_id?, device_id, period_id, time_in_minutes)` | POST; set daily limit (mins) for device. |
| `disable_time_limits_device(...)` | POST; disable all time limits for device (today). |
| `enable_time_limits_device(...)` | Calls `set_time_limits_device`; re-enable limits. |
| `lock_device(account_id?, device_id)` | POST; lock device. |
| `unlock_device(account_id?, device_id)` | POST; unlock device. |
| `enable_downtime_device(account_id?, device_id, start_*, end_*, period_id)` | POST; enable downtime (today). |
| `disable_downtime_device(...)` | POST; disable downtime (today). |

**Base**: `https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1`  
**Origin**: `https://familylink.google.com`  
**Device writes**: POST `/people/{account_id}/timeLimitOverrides:batchCreate`. `device_id` / `period_id` from `get_time_limits` or `get_apps_and_usage`.

---

## Models (High Level)

- **Members**: `Member`, `MembersResponse`, `Profile`, `MemberSupervisionInfo`, etc.
- **Apps**: `App`, `AppUsage`, `SupervisionSetting`, `UsageLimit`, `AlwaysAllowedAppInfo`, `AppUsageSession`, etc.
- **Devices**: `DeviceInfo`, `DeviceDisplayInfo`, `DeviceCapabilityInfo`.

---

## Tooling & CI

- **Ruff**: lint (`lint.yml` on push/PR).
- **Publish**: PyPI publish on release (`publish.yml`); version taken from tag, `uv` build/publish.
- **pre-commit**: config present; dev deps include `pre-commit`, `ruff`.

---

## Known Gaps

1. **CLI vs client API**: CLI calls `get_apps_and_usage()` with no args and uses `always_allow_app`, `set_app_limit`, `block_app`. The client requires `child_id` for `get_apps_and_usage` and does **not** implement those app-level write methods. Device APIs (time limits, lock/unlock, downtime) **are** implemented.
2. **Child selection**: `_ensure_account_id()` infers first non-self member for device APIs when `account_id` not set; otherwise use `get_members()` → `user_id`.
3. **Config editor**: `index.html` only edits CSV; it does not call the Family Link API.

---

## Dependencies

- **Runtime**: `browser-cookie3`, `httpx`, `pydantic`, `rich`.
- **Dev**: `pre-commit`, `ruff` (from `pyproject.toml`).
