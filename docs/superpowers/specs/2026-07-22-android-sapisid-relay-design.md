# Design: Android Bookmarklet SAPISID Relay

**Date:** 2026-07-22
**Status:** Approved

## Problem

`familylink export-cookies --coolify --restart` (README.md:447) is the documented fallback for refreshing the app's Google session, but it depends on `browser_cookie3` reading a real desktop Chrome profile file — a path that doesn't exist on Android (sandboxed browser storage, no root). The parent's phone is often the only device at hand when the session needs a quick refresh; there's currently no way to do this without a laptop.

## Constraint discovery

Explored and ruled out during brainstorming:
- **adb/CDP tethering** — still requires a computer present at refresh time; doesn't remove the laptop dependency.
- **Kiwi Browser + cookie-export extension** — works, but requires installing an extra browser app.
- **Termux CLI on-device** — Android sandboxes Chrome's cookie DB even with Termux installed; would still need an extension-export step first, more setup for no benefit.
- User's explicit steer: use the parent's **existing, already-signed-in Chrome**, and if a Termux/Python route isn't wanted, use a JavaScript bookmarklet instead.

## Solution

A `javascript:` bookmarklet, tapped from the parent's existing Android Chrome bookmarks, reads the `SAPISID` cookie from `document.cookie` (this cookie is deliberately not `HttpOnly` — Google's own web pages read it client-side to compute the `SAPISIDHASH` authorization header, the same mechanism `familylink`'s `CookieResolver` already relies on for its priority-2 raw-SAPISID auth path). The bookmarklet POSTs it as a plain HTML form (not `fetch`, so no CORS preflight) to a new token-authenticated endpoint on the main app, which hot-swaps the running `FamilyLinkService`'s client in-process — no container restart, no Coolify API involved.

This reuses two things that already exist and are proven:
- `FAMILYLINK_SAPISID` raw auth (`src/familylink/auth.py:1-10`, priority 2) — no new client-side auth logic needed.
- The hot-swap-without-restart pattern already used by `FamilyLinkService.reinit_with_cookies_b64` (`src/familylink_server/services/family_link.py:34`), which the automatic sidecar refresh loop already calls (`main.py:101`).

## Architecture

```
ONE-TIME SETUP
  [1] Generate a random token, set SAPISID_RELAY_TOKEN on the server
  [2] On a desktop browser signed into the same Google account as the parent's phone:
        create a bookmark whose URL is the javascript: bookmarklet (token baked in)
      → Chrome bookmark sync carries it to the parent's Android Chrome automatically

EACH REFRESH — parent, on their phone, no computer involved
  [1] Parent is (or becomes) signed into a Google property in Chrome, e.g. myaccount.google.com
  [2] Parent opens the bookmark (via Chrome's bookmarks/star menu)
  [3] bookmarklet: reads SAPISID from document.cookie
        → builds hidden <form method=POST target=_blank>, submits to
          POST https://<app>/admin/sapisid-relay  (fields: sapisid, token)
  [4] server: validates token (constant-time compare) →
        FamilyLinkService.reinit_with_sapisid(sapisid) →
        calls get_members() to verify the new session actually authenticates →
        clears auth_failed on success
  [5] new tab shows a small confirmation page: "✅ Reconnected" or "❌ <reason>"
      (original Google tab is untouched — form target is a new tab)
```

## Scope

**In scope:**
- `POST /admin/sapisid-relay` endpoint (`src/familylink_server/routers/admin.py`)
- `FamilyLinkService.reinit_with_sapisid()` (`src/familylink_server/services/family_link.py`)
- `SAPISID_RELAY_TOKEN` setting (`src/familylink_server/config.py`, `.env.example`)
- Bookmarklet source (documented in README, not a shipped file the server serves)
- Tests for the new endpoint and service method

**Out of scope:**
- Any general session-authenticated "paste SAPISID" web UI (the aspirational message in `discord_notifier.py:128` referencing a "web UI" stays unimplemented — separate future item, different auth model, not needed for this flow)
- Changing the automatic sidecar refresh loop, `reinit_with_cookies_b64`, or `export-cookies --coolify` (all remain as fallbacks for the "session fully expired, sidecar down too" case)
- A native app, PWA, or browser extension — the bookmarklet is the entire client-side surface

## New Files

None — all changes are additions to existing files.

## Modified Files

| File | Change |
|------|--------|
| `src/familylink_server/routers/admin.py` | Add `POST /admin/sapisid-relay`: reads form fields `sapisid`, `token`; 403 on token mismatch (`secrets.compare_digest`) or if `SAPISID_RELAY_TOKEN` unset; calls `service.reinit_with_sapisid(sapisid)`, then `get_members()` to verify; returns a minimal inline HTML success/failure page (no template dependency, no session-based auth on this route). |
| `src/familylink_server/services/family_link.py` | Add `reinit_with_sapisid(sapisid: str) -> None`: sets `FAMILYLINK_SAPISID` env var, pops `FAMILYLINK_COOKIES_B64`, rebuilds `self._client = FamilyLink()`, clears member/usage caches. Mirrors `reinit_with_cookies_b64`; does not clear `auth_failed` itself — caller verifies first. |
| `src/familylink_server/config.py` | Add `sapisid_relay_token: str = ''`. |
| `.env.example` | Add `SAPISID_RELAY_TOKEN=` with a comment. |
| `README.md` | New subsection under "Refreshing cookies via CLI": one-time bookmarklet setup (generate token, bookmarklet source, how to bookmark it so Chrome sync delivers it to Android), and the tap-to-refresh usage step. Explicit note that this only refreshes the *current session snapshot* — if Google has fully logged the account out, this won't help (same limitation as raw-SAPISID auth always had). |

## Key Implementation Details

**Why a plain form POST, not `fetch`:** a cross-origin `fetch`/`XHR` with a custom header or JSON body triggers a CORS preflight, which the server would need to answer correctly for `document.location.origin` (typically `https://myaccount.google.com`) — fragile and unnecessary. A classic HTML form submission is a normal cross-origin navigation, exempt from CORS entirely (the same mechanism that makes CSRF a problem elsewhere is what makes this simple here). The token field *is* this endpoint's CSRF protection — it must be unguessable and is the only thing standing between this route and being a public "reconnect with attacker-supplied SAPISID" endpoint.

**Token comparison:** use `secrets.compare_digest`, not `==`, to avoid timing side-channels — same reasoning as any bearer-token check, applied consistently with how `refresher_api_key` *should* be compared (existing `refresher_api_key` check in `admin.py:21` uses `!=`; not touching that in this change, out of scope, but the new endpoint uses the safer comparison from the start).

**Verify-before-success, matching existing discipline:** `reinit_with_cookies_b64`'s docstring already states the caller must verify via `get_members()` before trusting the new client. `reinit_with_sapisid` follows the same contract; the new endpoint is the caller and does the verification, returning the failure page (and leaving `auth_failed` untouched) if `get_members()` raises.

**Bookmarklet is documentation, not code shipped by this repo:** it lives in the README as a copy-pasteable `javascript:` URI template with a `{{TOKEN}}` placeholder the operator fills in once. No server route serves or generates it — keeps the token out of any response body/log.

## Testing

- `tests/server/test_routers_admin.py`: new endpoint — correct token + valid SAPISID → 200 confirmation page, `reinit_with_sapisid` and `get_members` called; wrong token → 403, `reinit_with_sapisid` not called; correct token but `get_members` raises → failure page, `auth_failed` unchanged; `SAPISID_RELAY_TOKEN` unset → 403 always.
- `tests/server/test_*` (service test file, likely alongside existing `FamilyLinkService` coverage): `reinit_with_sapisid` sets the env var, pops `FAMILYLINK_COOKIES_B64`, rebuilds the client, clears both caches.
- No automated test for the bookmarklet JS itself or actual Android Chrome bookmark-sync behavior — manual verification only (see below).

## Verification

1. Set `SAPISID_RELAY_TOKEN`, restart the app.
2. Build the bookmarklet URL with the real token, save it as a bookmark in a desktop Chrome signed into the same Google account as the parent's phone.
3. Confirm it appears in the parent's Android Chrome bookmarks (sync).
4. On the phone: open a Google property in Chrome, tap the bookmark, confirm a new tab opens showing "✅ Reconnected".
5. Confirm the app's dashboard reflects live data without any manual `FAMILYLINK_SAPISID`/Coolify restart.
6. Negative test: tap the bookmark while **not** signed into Google in that tab (no `SAPISID` cookie) — bookmarklet should alert instead of submitting.
7. **Flag before considering this fully done:** confirm tapping a synced bookmarklet actually executes `javascript:` on the parent's specific Android Chrome build/version — this is the one step whose behavior isn't guaranteed by spec and must be checked on the real device.
