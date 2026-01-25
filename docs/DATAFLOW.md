# Family Link Client — Dataflow & Functionality

## 1. CLI Dataflow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  config.csv     │────▶│  _load_config()  │────▶│  apps_config    │
│  (App,Duration, │     │  CSV → dict      │     │  {app: {sched,  │
│   Days,Ranges)  │     │  _parse_days()   │     │   limits,       │
└─────────────────┘     │  _parse_duration │     │   always_allowed│
                        └──────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  FamilyLink     │◀────│  _get_expected_  │◀────│  datetime.now() │
│  client         │     │  limits(config)  │     │  today, current │
│                 │     │  • today + time  │     │  time           │
│  get_apps_      │     │  • schedule eval │     └─────────────────┘
│  and_usage()    │     │  → expected_     │
│                 │     │    limits        │
└────────┬────────┘     └──────────────────┘
         │
         │  (conceptual: current client requires child_id;
         │   CLI assumes no-arg + AppUsage-like response)
         ▼
┌─────────────────┐     ┌──────────────────┐
│  app_usage      │────▶│  _apply_config() │
│  .apps[]        │     │  • diff expected │
│  supervision_   │     │    vs current    │
│  setting        │     │  • always_allow  │
└─────────────────┘     │  • set_app_limit │
                        │  • block_app     │
                        └────────┬────────┘
                                 │
                      ┌──────────┴──────────┐
                      │  --dry-run: log     │
                      │  else: client calls │
                      └────────────────────┘
```

### Steps

1. **Load config**  
   `config.csv` → `_load_config()` → `apps_config`: per-app schedules, limits, `always_allowed`.

2. **Compute expected limits**  
   `_get_expected_limits(config)` uses `datetime.now()` (today, time). For each app:
   - `always_allowed` → `True`
   - Else: if today has a limit and (no schedule or current time in range) → limit (minutes).

3. **Fetch current state**  
   CLI calls `client.get_apps_and_usage()` (conceptually; current client needs `child_id`). Builds `current_limit_per_app` from `app.supervision_setting`:
   - `usage_limit` → minutes
   - `hidden` → `False` (blocked)
   - `always_allowed_app_info` + `ENABLED` → `True`
   - Unsupervised (non-Google/Android) → `None`

4. **Apply diff**  
   For each app:
   - Expected == current → no op (log "already set").
   - Expected `True` → `always_allow_app(app)`.
   - Expected int → `set_app_limit(app, mins)`.
   - Else (block) → `block_app(app)`.  
   `--dry-run`: only log; no client writes.

5. **Bootstrap config**  
   If config file missing, `_create_default_config()` uses `get_apps_and_usage()` → writes `config.csv` with all apps, `0:00`, empty days/ranges.

---

## 2. Client → Google API Dataflow

```
┌─────────────────────────────────────────────────────────────────┐
│  FamilyLink.__init__()                                           │
│  • Resolve SAPISID: sapisid.txt | cookies.txt | FAMILYLINK_*     │
│  • browser="txt": cookies from file only (no browser)            │
│  • Else: browser_cookie3 (host only, no profile dir)             │
│  • Build Authorization: SAPISIDHASH = f"{ts}_{sha1(...)}"        │
│  • httpx.Client + Origin, X-Goog-Api-Key, cookies                │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  Kids Management API (HTTPS)                                     │
│  Base: .../kidsmanagement/v1                                     │
│  Origin: https://familylink.google.com                           │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
  GET /families/       GET /people/{id}/    GET /people/{id}/
  mine/members         appsandusage         timeLimit /
         │                    │              appliedTimeLimits
         ▼                    ▼                    │
  MembersResponse      Raw JSON                    ▼
  (members[])          (apps, usage,         Raw JSON
  → print_usage()       devices)                   │
         │                    │                    │
         └────────────────────┴────────────────────┘
                              │
         ┌────────────────────┴────────────────────┐
         ▼  POST /people/{id}/timeLimitOverrides:batchCreate
  Device write APIs (today’s overrides):
  • set_time_limits_device, disable_time_limits_device,
    enable_time_limits_device (limit mins, device_id, period_id)
  • lock_device, unlock_device (device_id)
  • enable_downtime_device, disable_downtime_device
    (device_id, start/end hour+minute, period_id)
```

- **Auth**: SAPISID + SHA1-based `SAPISIDHASH` in `Authorization` header.
- **Device APIs**: POST to `timeLimitOverrides:batchCreate`; `account_id` from `_ensure_account_id()` (or `get_members()` → `user_id`); `device_id` / `period_id` from `get_time_limits` / `get_apps_and_usage`.
- **App-level** (`set_app_limit`, `block_app`, `always_allow_app`): still not in client; CLI expects them.

---

## 3. Config Editor (index.html) Dataflow

```
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  config.csv      │────────▶│  fetch / load    │────────▶│  configData[]    │
│  (optional)      │         │  or drag-drop    │         │  {app, duration, │
└──────────────────┘         └──────────────────┘         │   days, timeRange│
                                                          └────────┬─────────┘
                                                                   │
                                                                   ▼
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  Save to CSV     │◀────────│  renderTable()   │◀────────│  Add/Delete/Edit │
│  (download)      │         │  Editable rows   │         │  rows            │
└──────────────────┘         └──────────────────┘         └──────────────────┘
```

- **Load**: initial `fetch('config.csv')` or drag-drop CSV → `loadCSVData()` → `configData` → table.
- **Edit**: inline inputs → `updateData()` → `configData`.
- **Save**: `saveToCSV()` builds `App,Max Duration,Days,Time Ranges` CSV and triggers download.
- **No API**: editor only manipulates CSV; it does not call Family Link or the Python client.

---

## 4. Model Usage in Code

| Model | Used in | Purpose |
|-------|---------|---------|
| `MembersResponse`, `Member`, `Profile` | `client.get_members()`, `print_usage()` | Family members, emails, `user_id` |
| `AppUsage`, `App`, `SupervisionSetting`, `UsageLimit`, `AlwaysAllowedAppInfo`, `AlwaysAllowedState` | CLI `_apply_config()`, config logic | Parse app list, limits, blocked, always-allowed |
| `AppId`, `AppUsageSession`, `UsageDate`, `DeviceInfo` | `AppUsage` | Nested app usage and device data |

---

## 5. End-to-End Flow (Intended)

1. User logs into Family Link in browser (or provides `sapisid` / `cookies`; or `browser="txt"` + `cookies.txt`).
2. User edits `config.csv` (by hand or via `index.html`).
3. User runs `familylink config.csv` (or `--dry-run`).
4. CLI loads config → computes expected limits for “now” → fetches current app state (needs `child_id`) → diffs → calls `always_allow_app` / `set_app_limit` / `block_app` (when implemented).

**Device APIs**: Implemented. Use `get_members()` → `user_id` as `account_id`; `get_time_limits` / `get_apps_and_usage` for `device_id` and `period_id`. `_ensure_account_id()` infers first non-self member when `account_id` not set.

**Gap**: App-level writes (`set_app_limit`, `block_app`, `always_allow_app`) still not in client; CLI expects them.
