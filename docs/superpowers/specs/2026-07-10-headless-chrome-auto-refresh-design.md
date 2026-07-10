# Design: Headless Chrome Auto-Cookie-Refresh

**Date:** 2026-07-10
**Status:** Approved

## Problem

When the Family Link Google session expires, the existing `/admin/reconnect` UI accepts only a raw `SAPISID` value. This fails in Coolify deployments because `FAMILYLINK_COOKIES_B64` (the full stale cookie jar) is already set in the environment and takes priority — the resolver loads the stale jar, overwrites the fresh SAPISID into it, but HSID/SSID/APISID remain expired. Google rejects the request.

The CLI command `familylink export-cookies --base64 --coolify --restart` works because it replaces the entire cookie jar. The UI needs an equivalent path that requires zero manual action.

## Solution

A **sidecar Docker service** (`cookie-refresher`) runs Playwright + Chromium. When `health_check_loop` in the main server detects `SessionExpiredError`, it calls the sidecar's `POST /refresh` endpoint. The sidecar logs into Google using stored credentials + TOTP, extracts all cookies, and returns them as a base64 Netscape cookies.txt. The main server hot-reloads `FamilyLinkService` with `reinit_with_cookies_b64()`.

**Why sidecar, not inline:** Chromium adds ~500MB to the Docker image. Main server image stays lean.

**Scope excludes:** CLI changes, `/admin/reconnect` changes, Coolify persistence (hot-reload only, not pushed back to Coolify env vars).

## Architecture

```
main server (familylink-server)
    health_check_loop detects SessionExpiredError
    └─► _try_auto_refresh(service, notifier) → bool
          └─► httpx.post(COOKIE_REFRESHER_URL + "/refresh", timeout=120)
                └─► sidecar (familylink-cookie-refresher)
                      cookie_refresher_app.py
                      reads env: GOOGLE_EMAIL, GOOGLE_PASSWORD, TOTP_SECRET
                      Playwright sync_playwright()
                        chromium.launch(headless=True)
                        login flow: email → password → TOTP (pyotp.TOTP)
                        context.cookies() → Netscape format → base64
                      returns {"cookies_b64": "..."}
          └─► service.reinit_with_cookies_b64(cookies_b64)
                sets FAMILYLINK_COOKIES_B64 in os.environ
                pops FAMILYLINK_SAPISID
                recreates FamilyLink() client
                clears caches, resets auth_failed
          └─► _alert_active = False (in caller)
          └─► notifier.notify_session_restored()
```

## Degradation

- `COOKIE_REFRESHER_URL` not set → `_try_auto_refresh` is a no-op, existing behavior preserved
- Sidecar down/unreachable → logs error, `auth_failed` stays True, Discord alert stays active
- Google blocks headless Chrome (CAPTCHA) → same as above; manual reconnect still works
- Wrong credentials → 500 from sidecar → same as above

## New Files

| File | Purpose |
|------|---------|
| `Dockerfile.refresher` | Sidecar image: Python 3.13-slim + `pip install ".[refresher]"` (base + playwright/pyotp/fastapi/uvicorn) + Playwright Chromium binary |
| `src/familylink_server/cookie_refresher_app.py` | FastAPI: `POST /refresh`, `GET /health` |

## Modified Files

| File | Change |
|------|--------|
| `pyproject.toml` | Add `[refresher]` optional dep group: `playwright>=1.40`, `pyotp>=2.9`, `fastapi`, `uvicorn` |
| `src/familylink_server/config.py` | Add `cookie_refresher_url: str = ""` |
| `src/familylink_server/services/family_link.py` | Add `reinit_with_cookies_b64(cookies_b64: str)` method |
| `src/familylink_server/main.py` | Add `_try_auto_refresh()` helper; update `health_check_loop` to call it and reset `_alert_active` on success |

## New Env Vars

| Service | Var | Notes |
|---------|-----|-------|
| main server | `COOKIE_REFRESHER_URL` | `http://<sidecar-service>:8080` in Coolify internal network |
| sidecar | `FAMILYLINK_GOOGLE_EMAIL` | Same Google account as main |
| sidecar | `FAMILYLINK_GOOGLE_PASSWORD` | Google account password |
| sidecar | `FAMILYLINK_TOTP_SECRET` | Base32 seed from Authenticator; get via myaccount.google.com → Security → 2-Step Verification (re-enroll to see seed) |

## Key Implementation Details

**`reinit_with_cookies_b64` vs existing `reinit_with_cookies`:**
The existing method sets `FAMILYLINK_SAPISID` but the stale `FAMILYLINK_COOKIES_B64` jar still loads and contaminates the session. The new method replaces `FAMILYLINK_COOKIES_B64` and pops `FAMILYLINK_SAPISID` — full jar wins cleanly.

**`_alert_active` reset:**
`_try_auto_refresh` returns `bool`. Caller in `health_check_loop` resets `_alert_active = False` on `True` return, preventing duplicate `notify_session_restored()` calls on the next successful health check.

**Playwright TOTP selector:**
Uses `input[type="tel"], input[type="number"]` — broad enough to catch Google's 2FA input variants. If Google changes login page HTML, update selectors in `cookie_refresher_app.py`.

**`httpx` in main server:**
Already a transitive dep (used by familylink client). No new dep in main image.

**No retry, no playwright-stealth.** Both can be added if needed after initial deployment.

## Verification

1. `curl -X POST http://<sidecar>:8080/refresh` — should return `{"cookies_b64": "..."}`
2. In main server, temporarily clear `FAMILYLINK_COOKIES_B64` + restart → next health check detects expiry → auto-refresh triggers
3. Logs: `Auto-refresh: calling sidecar` → `Auto-refresh: success`
4. Discord: restored notification
5. Family Link data loads without manual intervention
