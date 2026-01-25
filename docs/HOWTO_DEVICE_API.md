# Device APIs — PR #7 (Add locking and time control)

Implemented in [PR #7](https://github.com/tducret/familylink/pull/7). All modify **today’s** settings. Author reports endpoints tested.

---

## Endpoint

**POST** `{BASE_URL}/people/{account_id}/timeLimitOverrides:batchCreate`

Same path for all 7 actions; payload shape differs. `account_id` = child (use `get_members()` → `user_id`). `device_id` from e.g. `get_apps_and_usage` / `appliedTimeLimits` → `device_info`.

---

## Methods

| Method | Purpose | Key payload |
|--------|---------|-------------|
| `get_time_limits(account_id)` | GET applied limits | GET `/people/{id}/appliedTimeLimits` |
| `set_time_limits_device(account_id, device_id, period_id, time_in_minutes)` | Set daily limit (mins) | `[[...,8,device_id,...,[2,time_in_minutes,period_id]]]` |
| `disable_time_limits_device(...)` | Disable all limits | `[1,time_in_minutes,period_id]` in override |
| `enable_time_limits_device(...)` | Restore limits | calls `set_time_limits_device` |
| `lock_device(account_id, device_id)` | Lock device | `[[None,None,1,device_id]]` |
| `unlock_device(account_id, device_id)` | Unlock device | `[[None,None,4,device_id]]` |
| `disable_downtime_device(account_id, device_id, start_*, end_*, period_id)` | Disable downtime | `[1,[start_hour,end_minute],[end_hour,end_minute],period_id]` |
| `enable_downtime_device(...)` | Enable downtime | `[2,[start_hour,end_minute],[end_hour,end_minute],period_id]` |

`period_id`: from `get_time_limits` / `appliedTimeLimits` response.

---

## Cookie file only (no browser sync)

PR adds `browser="txt"`:

- Uses `cookies.txt` (default `./cookies.txt` or `cookie_file_path`).
- `MozillaCookieJar` load — no browser_cookie3. For HA / headless: copy one cookie file instead of syncing browser.

---

## Adding more actions (no hallucination)

1. **Capture**: DevTools → Family Link UI → trigger action → note **method, path, body**.
2. **Implement**: Add client method; use only captured path/body.
3. **Verify**: Mock test + manual check in Family Link.

No implementation without captured traffic.
