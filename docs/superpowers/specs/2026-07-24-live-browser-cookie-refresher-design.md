# Live-Browser Cookie Refresher — Design

**Date:** 2026-07-24
**Status:** Approved (design)
**Supersedes:** `2026-07-10-headless-chrome-auto-refresh-design.md`, `2026-07-11-persisted-session-refresher-design.md`

## Problem

The auto-refresh sidecar never restores the Family Link session. Only the manual
CLI path (`familylink export-cookies --coolify --restart`) works.

### Root cause (proven)

The sidecar replays a **frozen snapshot** of a Google session
(`/data/state.json`) through headless Chromium, re-extracts cookies, and returns
them. This cannot work long-term:

- A snapshot holds a stale **bound, rotating token** (`__Secure-1PSIDTS` /
  `__Secure-3PSIDTS`). It never rotates the token itself.
- Google's risk engine revokes the frozen lineage server-side once the source
  browser rotates past it (or on any security event). Cookie `expires`
  timestamps stay far in the future (2027) but the **session is dead**.
- `myaccount.google.com` (lenient) still shows a `SAPISID`, so the sidecar's weak
  liveness check passes and it happily returns dead cookies. The sensitive
  `kidsmanagement-pa` API rejects them → `verification: HTTP 401`.

Evidence gathered against the live deployment:

| Check | Result | Conclusion |
|-------|--------|-----------|
| Bootstrap conversion drops cookies? | No — all 63 present | not a conversion bug |
| `state.json` cookie expiry | valid to 2027 | not "cookies expired" |
| Fresh home-browser cookies, raw verify | PASS | account is alive |
| Fresh home cookies through full nav/replay | PASS | replay code is fine |
| **Server `state.json`, raw verify (no nav)** | **FAIL 401** | **stored session revoked** |

The last row is decisive: the stored session fails the API with **no navigation
involved**. The replay/nav is irrelevant — the snapshot is a corpse.

The CLI works only because it injects a **freshly exported, currently-live**
session each time and uses it before Google rotates it away.

### Why a live browser fixes it

A phone and laptop stay logged into the same Google account for months side by
side. They survive because each is a **live browser continuously rotating its own
bound token** — never frozen. The fix is therefore: **do not clone a session;
keep a real one alive.**

## Goals

- Auto-refresh that survives Google's token rotation indefinitely.
- Runs entirely server-side (no dependency on the operator's laptop or a home
  machine).
- Reuses the one proven-working mechanism: reading cookies from a real, live
  browser profile.
- Honest failure: on a genuinely dead session, alert and back off — never loop
  500s.

## Non-goals

- Automating Google login (Google blocks scripted sign-in; login stays a rare,
  interactive, human step).
- Supporting the old snapshot/bootstrap model (removed).

## Architecture

Two containers replace the doomed replay sidecar.

```
┌─ firefox (persistent, headful) ───────────────┐
│  linuxserver/firefox image + noVNC             │
│  logged into parent Google ONCE via noVNC      │
│  self-warms: pinned Google tab auto-reloads    │
│  profile on a volume → cookies.sqlite (LIVE)   │
└───────────────┬────────────────────────────────┘
                │ shared volume (refresher reads profile, read-only)
┌─ cookie-refresher (rewritten, tiny) ───────────┐
│  POST /refresh                                  │
│    → browser_cookie3.firefox(cookie_file=…)     │
│    → filter google.com → verify vs kidsmgmt     │
│    → return {cookies_b64}                        │
│  no Playwright, no /bootstrap, no snapshot      │
└───────────────┬────────────────────────────────┘
                │ existing contract (unchanged): POST /refresh → {cookies_b64}
┌─ web (main app) ───────────────────────────────┐
│  _try_auto_refresh → reinit_with_cookies_b64    │
│  + proactive refresh every ~12h (cookies live)  │
│  + backoff + "re-login via noVNC" alert         │
└─────────────────────────────────────────────────┘
```

## Components

Each unit has one purpose, a defined interface, and is independently testable.

### 1. `firefox` container (config only)

- **Purpose:** hold a live, logged-in parent Google session and keep it warm.
- **Interface:** a profile volume (read by the refresher) and a noVNC web UI (for
  the one-time login).
- **Depends on:** the `linuxserver/firefox` (or equivalent) image; a persistent
  volume; Traefik/Coolify for the protected noVNC route.
- **Self-warm:** a pinned Google Account tab configured to auto-reload on a timer
  so Firefox keeps rotating `__Secure-1PSIDTS`. (Exact mechanism validated in the
  spike; fallback is an explicit reload cron in the container.)
- No application code lives here.

### 2. `cookie_refresher_app.py` (rewritten)

- **Purpose:** expose the live profile's cookies as verified `cookies_b64`.
- **Interface:**
  - `GET /health` → liveness.
  - `POST /refresh` (X-Api-Key protected, contract unchanged) →
    `{"cookies_b64": "..."}` on success.
- **Behavior:**
  1. Locate the Firefox profile `cookies.sqlite` on the shared volume.
  2. Read via `browser_cookie3.firefox(cookie_file=<path>)`; filter to
     `google.com` domains.
  3. Verify with `_verify_family_link_access` (kept) — the **real** gate.
  4. Return base64 Netscape cookies.
- **Removed:** `_get_cookies_b64` (Playwright nav/re-extract), `StorageState`,
  `/bootstrap`, all `playwright` usage.
- **Depends on:** `browser_cookie3` (firefox backend), the `familylink` client
  (for verification), the shared profile volume.

### 3. `Dockerfile.refresher`

- **Purpose:** build the refresher image.
- **Change:** drop `playwright install --with-deps chromium`; install
  `browser_cookie3` (firefox reader) instead. Image becomes small.

### 4. `web` (main app) changes

- **Purpose:** consume fresh cookies and hot-reload; fail honestly.
- **Changes:**
  - `_try_auto_refresh`: contract unchanged (still `POST {url}/refresh`).
  - Add a **proactive refresh** task (~every 12h): because the live session is
    always fresh, rotate `FAMILYLINK_COOKIES_B64` well before natural expiry so a
    hard 401 is never reached.
  - Add **exponential backoff** when `/refresh` returns a dead-session error, so
    the app stops hammering `/refresh` (today it loops 500s).
  - Alert / 503 page message points to the **noVNC login URL** ("sign in again in
    the browser") instead of the CLI re-export instructions.

### 5. Removed

- `scripts/bootstrap_refresher_session.py` — the snapshot concept is gone.
  Replaced by a documented one-time noVNC login procedure in the README.

## Data flow

- **Login (one-time / rare):** operator opens the protected noVNC URL → signs
  into the parent Google account headful (passes Google's anti-automation block)
  → profile persists on the volume. Repeated only if the session is fully killed
  (password change, explicit sign-out, security event).
- **Refresh (routine, automatic):** health-check 401 *or* the 12h proactive timer
  → `web` calls refresher `/refresh` → refresher reads the **live** profile
  cookies, verifies against `kidsmanagement-pa`, returns `cookies_b64` → `web`
  calls `reinit_with_cookies_b64` → session restored. No restart, no replay.

## Error handling

| Condition | Refresher response | Web app behavior |
|-----------|--------------------|------------------|
| Profile missing / never logged in | `409` "not logged in — open noVNC" | set `auth_failed`, alert with noVNC URL, back off |
| `cookies.sqlite` locked | copy DB (browser_cookie3 default); one retry | n/a |
| Live cookies fail verify (session dead) | `502`/`500` dead-session error | set `auth_failed`, alert with noVNC URL, **exponential backoff** |
| Refresh success | `200 {cookies_b64}` | hot-reload, clear `auth_failed`, "restored" alert |

## Security

**The `firefox` container holds a fully logged-in parent Google session.** Access
to its noVNC UI is equivalent to full control of that Google account. This is a
**larger exposure than the old snapshot** and must be locked down:

- noVNC route behind auth (Traefik basic-auth) and **not** publicly exposed;
  prefer reachable only via the internal network / SSH tunnel.
- The profile volume is sensitive at rest (holds live session tokens); treat like
  a credential store.
- `REFRESHER_API_KEY` still gates `/refresh`.

The README security section must call this out explicitly.

## Testing

- **Unit (`tests/server/test_cookie_refresher.py`, rewritten):**
  - `/refresh` reads a fixture `cookies.sqlite` and returns `cookies_b64`
    (FamilyLink verification mocked to succeed).
  - Not-logged-in / missing profile → `409`.
  - Dead session (verification raises) → dead-session error path; web app applies
    backoff.
  - Remove all Playwright/`/bootstrap` tests.
- **Spike (validates the core assumption — do first):** stand up the `firefox`
  container, log into the parent account, `curl /refresh` → confirm
  `{cookies_b64}` authenticates. **Re-verify after 2-3 days** that the warm
  session still authenticates. If warming is insufficient, add an explicit
  keep-alive reload in the container and re-test.

## Open assumptions to validate

1. **Warm-session longevity** — a containerized Firefox with a pinned,
   auto-reloading Google tab keeps `__Secure-1PSIDTS` rotating and the session
   valid for `kidsmanagement-pa` over days/weeks. Validated by the spike;
   fallback is an explicit reload cron.
2. **Cookie read while running** — `browser_cookie3.firefox` reliably reads
   `cookies.sqlite` from a live Firefox (it copies the DB to avoid lock
   contention). Confirmed by unit fixture + spike.

## Rollout

1. Build the `firefox` container + rewritten refresher; deploy alongside current
   web app.
2. Run the spike; confirm `/refresh` works and survives 2-3 days.
3. Cut `web` over to the new refresher (contract is unchanged, so this is
   low-risk); remove Playwright/bootstrap code and tests.
4. Update README (one-time noVNC login procedure + security warning); delete the
   snapshot bootstrap docs.
