# Design: Persisted-Session Cookie Refresher (replaces password+TOTP login)

**Date:** 2026-07-11
**Status:** Approved
**Supersedes:** `2026-07-10-headless-chrome-auto-refresh-design.md` (login-flow portion only; architecture/hot-reload plumbing from that design is unchanged)

## Problem

The `cookie-refresher` sidecar's `/refresh` endpoint automates a Google username/password + TOTP login via headless Chromium. In production this reliably fails: after correctly filling the identifier field, Google returns "Couldn't sign you in — This browser or app may not be secure." Reproduced locally too, headed, from a residential IP — ruling out IP reputation and headless-mode as the cause. This is Google's deliberate anti-automation policy (detects `navigator.webdriver` / CDP fingerprints), not a fixable selector or stealth-patch problem. Repeated blocked attempts also risk Google flagging the account for suspicious sign-in activity.

## Solution

Stop automating login. Bootstrap the sidecar's session **once** from a real, already-authenticated browser (no automation touches the login form at all), persist it to a Docker volume, and have `/refresh` replay those cookies through a real Playwright page load to let Google reissue fresh short-lived tokens — the same mechanism that keeps a normal browser tab "logged in" for weeks while specific API tokens rotate silently underneath.

**Why this avoids the block:** bootstrap uses `browser_cookie3` (same library `familylink export-cookies` already uses) to read cookies directly from the operator's real Chrome profile. No Playwright browser ever submits Google's login form with credentials — there is nothing for Google's automated-sign-in detector to catch.

## Architecture

```
ONE-TIME (or rare re-auth) — operator, on their laptop
  [1] Log into Google normally in real Chrome
  [2] scripts/bootstrap_refresher_session.py
        browser_cookie3.chrome() → filter google.com cookies
        → convert to Playwright storage_state JSON
        → POST to web app
  [3] web app: POST /admin/refresher-bootstrap (X-Api-Key auth)
        → proxies body to sidecar's internal POST /bootstrap
  [4] sidecar: POST /bootstrap
        → writes storage_state JSON to volume (/data/state.json)

AUTOMATIC — forever after, no human involved
  health_check_loop (every 30 min) detects SessionExpiredError
  └─► _try_auto_refresh() → sidecar POST /refresh
        → load /data/state.json into new Playwright context
        → page.goto('https://myaccount.google.com/', wait_until='networkidle')
        → extract context.cookies(), verify SAPISID present
        → write updated storage_state back to /data/state.json (persist rotation)
        → return {"cookies_b64": ...}
  └─► service.reinit_with_cookies_b64(cookies_b64)
  └─► Discord "✅ restored" notification

  failure paths (state.json missing, or no SAPISID after nav):
  → existing manual /admin/reconnect (paste SAPISID) remains the fallback
  → or operator re-runs bootstrap (steps 1-4)
```

## Scope

**In scope:** rewrite `cookie_refresher_app.py`'s login flow; new `/bootstrap` endpoint on sidecar; new `/admin/refresher-bootstrap` proxy endpoint on main app; new `scripts/bootstrap_refresher_session.py`; Docker volume for sidecar state; remove password+TOTP code path and its env vars.

**Out of scope:** changes to `health_check_loop`'s polling/alerting logic, `reinit_with_cookies_b64`, the existing manual `/admin/reconnect` UI, or the CLI's `export-cookies` command (bootstrap script reuses its cookie-extraction approach but is a separate standalone script, not a CLI subcommand — YAGNI, this is an infrequent operator action).

## New Files

| File | Purpose |
|------|---------|
| `scripts/bootstrap_refresher_session.py` | Operator-run: extract cookies via `browser_cookie3`, convert to Playwright `storage_state` JSON, POST to `/admin/refresher-bootstrap` |

## Modified Files

| File | Change |
|------|--------|
| `src/familylink_server/cookie_refresher_app.py` | Remove `_get_cookies_b64`'s password/TOTP login flow. Add `POST /bootstrap` (writes request body to `STATE_PATH`, default `/data/state.json`). Rewrite `/refresh` to load `STATE_PATH` into a Playwright context via `storage_state=`, navigate to `myaccount.google.com`, verify SAPISID, write rotated state back, return cookies. Remove `pyotp` import. |
| `src/familylink_server/routers/admin.py` | Add `POST /admin/refresher-bootstrap`, protected by `X-Api-Key` against `settings.refresher_api_key` (not `require_user` — this is operator/script-driven). Proxies request body via `httpx` to `{settings.cookie_refresher_url}/bootstrap`. |
| `docker-compose.yml` | Add named volume (e.g. `refresher_state`) mounted at `/data` on `cookie-refresher`. Remove `FAMILYLINK_GOOGLE_PASSWORD`/`FAMILYLINK_TOTP_SECRET` from its environment. |
| `pyproject.toml` | Remove `pyotp` from `[refresher]` extra. |
| `.env.example` | Remove `FAMILYLINK_GOOGLE_PASSWORD`/`FAMILYLINK_TOTP_SECRET`. |
| `tests/server/test_cookie_refresher.py` | Replace login-flow tests with bootstrap/refresh-from-state tests (fake Playwright objects, same pattern as existing tests). |
| `README.md` | Already updated with the new flow diagram and deployment steps (this commit). |

## Removed

- Password+TOTP login flow in `_get_cookies_b64`
- `pyotp` dependency
- `FAMILYLINK_GOOGLE_PASSWORD`, `FAMILYLINK_TOTP_SECRET` env vars

## Key Implementation Details

**`storage_state` format:** Playwright expects `{"cookies": [{name, value, domain, path, expires, httpOnly, secure, sameSite}, ...], "origins": []}`. `browser_cookie3`'s `http.cookiejar.Cookie` objects map to this; `sameSite` isn't available from `browser_cookie3` — default to `'None'` (valid since all relevant Google auth cookies are `Secure`).

**`/bootstrap` write is last-write-wins**, no merge logic — a fresh bootstrap fully replaces the persisted state.

**`/refresh` persists rotation:** after each successful refresh, the sidecar overwrites `STATE_PATH` with the navigated context's current `storage_state()`, so subsequent refreshes use the freshest cookies rather than replaying the original bootstrap forever.

**Auth asymmetry is intentional:** `/admin/refresher-bootstrap` on the main app uses `X-Api-Key` (matches how the sidecar's own endpoints are protected) rather than `require_user`, because it's invoked by a standalone script, not a browser holding an `fl_session` cookie.

## Testing

- `cookie_refresher_app.py`: fake Playwright context/page (same style as existing tests) for `/refresh` reading a fake `state.json`, verifying SAPISID, writing rotated state back; `/bootstrap` writing request body to `STATE_PATH`; missing-state-file error path.
- `admin.py`: `/admin/refresher-bootstrap` — correct/incorrect `X-Api-Key`, verifies proxy call to sidecar with `httpx` mocked.
- No test coverage possible for the real `browser_cookie3` extraction or actual Google navigation (external, credential-bearing) — verified manually per the Verification section below.

## Verification

1. Bootstrap: run `scripts/bootstrap_refresher_session.py` against a local Chrome logged into the parent account; confirm `/data/state.json` appears on the sidecar volume.
2. `curl -X POST -H "X-Api-Key: <key>" http://<sidecar>:8080/refresh` → `{"cookies_b64": "..."}` within ~30s, no login form involved.
3. Main app: clear `FAMILYLINK_COOKIES_B64`, restart, wait for next health check → auto-refresh triggers → Discord "✅ restored".
4. Family Link data loads without manual intervention.
