# OAuth Bearer Auth + Session Resilience — Design Spec

**Date:** 2026-06-30
**Status:** Approved

## Problem

The Family Link server authenticates against Google's private `kidsmanagement-pa` API using browser session cookies (`FAMILYLINK_COOKIES_B64`). These cookies expire unpredictably (days to months — Google controls the TTL). When they expire:

- Every route raises `SessionExpiredError`, rendering a 503 page
- The Discord daily summary stops posting silently
- The Linux machine poller loses its data source but holds last known state
- Kids can exploit the enforcement gap before the parent notices
- Recovery requires: `familylink export-cookies --browser chrome --base64 --coolify --restart` from a desktop Mac — not possible on mobile

## Goals

1. Detect session expiry immediately and alert via Discord
2. Allow session renewal from any browser (mobile or desktop) — no CLI required
3. Replace cookie-based auth with OAuth Bearer token + stored refresh_token so the server auto-renews indefinitely

## Non-Goals

- Server-side Playwright/browser automation (stores credentials on server, ToS risk)
- Extending Google cookie TTL (not possible — Google controlled)
- OAuth scopes for Family Link (no public scopes exist; this design uses any valid Google OAuth access token)

## Key Discovery

Google's internal APIs have two authentication paths. The web path uses `Authorization: SAPISIDHASH {hash}` derived from browser cookies. The mobile path (used by the official Family Link app) uses `Authorization: Bearer ya29.{access_token}` — a standard Google OAuth access token, no cookies required, no special Family Link scope needed.

**PoC gate:** The first implementation task must validate this empirically. If `GET /kidsmanagement/v1/families/mine/members` with `Authorization: Bearer {google_oauth_access_token}` returns 200, full implementation proceeds. If 401/403, the design falls back to the hot-reload endpoint + iOS Shortcut path (Fallback B).

---

## Architecture

### Auth Priority (new)

```
1. DB refresh_token  →  auto-fetch access_token  →  Bearer auth   [primary]
2. FAMILYLINK_COOKIES_B64 env var                →  SAPISIDHASH   [backward compat]
3. Existing cookie chain (FAMILYLINK_SAPISID, file, browser_cookie3)
```

Existing deployments keep working during migration. The DB token takes precedence once set.

### Component Map

```
parent browser (mobile or desktop)
  │
  ├─► 503 "Google session expired" page
  │     └─► "Reconnect Google Session" button
  │           └─► GET /auth/reauth  ──► Google OAuth (access_type=offline, prompt=consent)
  │                                        └─► GET /auth/callback
  │                                              ├─► store refresh_token in app_configs DB
  │                                              ├─► reinit FamilyLinkService (no restart)
  │                                              └─► redirect → /  (dashboard)
  │
  └─► Dashboard  (auth status indicator: green / red dot)

background tasks (lifespan)
  ├─► health_check_loop  (every 30 min)
  │     ├─► get_members() probe
  │     ├─► on failure → Discord alert + set auth_failed flag
  │     └─► on recovery → Discord "restored" alert + clear flag
  │
  └─► token_refresh  (inside FamilyLinkService, per-call)
        └─► if access_token expired → POST google token endpoint with refresh_token
              └─► update cached access_token + expiry in DB
```

---

## Section 1 — OAuth Bearer Token Auth

### `familylink/auth.py`

Add `OAuthResolver` alongside the existing `CookieResolver`. Takes an `access_token` string and returns it directly — no cookie parsing, no SAPISID extraction. `CookieResolver` is unchanged.

### `familylink/client.py`

`FamilyLink.__init__` gains an `oauth_token: str | None = None` parameter. When provided:

```python
self._headers = {
    "User-Agent": "Mozilla/5.0",
    "Origin": self.ORIGIN,
    "Content-Type": "application/json+protobuf",
    "Authorization": f"Bearer {oauth_token}",
}
self._cookies = None
```

No `X-Goog-Api-Key` header (Bearer token carries project context). No cookie jar. The SAPISIDHASH path is retained when `oauth_token` is `None` — full backward compat.

### `familylink_server/services/family_link.py`

`FamilyLinkService` gains token lifecycle management:

- `_access_token: str | None` — cached, valid for 1 hour
- `_token_expiry: datetime | None`
- `async _ensure_token() -> str` — if expired or missing, calls `POST https://oauth2.googleapis.com/token` with stored refresh_token via `httpx.AsyncClient`; updates DB and cache
- Before every API call: `await self._ensure_token()`, reconstruct client headers if token changed

`reinit_with_token(refresh_token: str)` — public method called after OAuth callback to hot-swap credentials without restart.

`init_service()` in `main.py` checks DB for a stored refresh_token on startup; if found, initialises in OAuth mode. Otherwise falls back to cookie mode.

### DB storage

New `OAuthToken` model in `db/models.py`:

```python
class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

**Alembic migration required.** One new migration script under `alembic/versions/` that creates the `oauth_tokens` table.

Note: `app_configs` is a structured per-app config table — not a key/value store. Token storage belongs in its own table.

---

## Section 2 — Re-auth Flow

### 503 page update (`main.py`)

The `session_expired_handler` HTML gains a "Reconnect Google Session" button that links to `GET /auth/reauth`. This is the entry point for both mobile and desktop parents. No login required to reach this page — it is already the unauthenticated error surface.

### New route: `GET /auth/reauth`

Added to `auth/oauth.py`. Triggers Google OAuth with:
- `access_type=offline`
- `prompt=consent` (forces refresh_token issuance even if previously granted)
- Same `redirect_uri` as the existing callback

### OAuth callback update (`GET /auth/callback`)

After validating the email (existing check), also:
1. Extract `refresh_token` from the token response
2. Write to `app_configs` DB
3. Call `service.reinit_with_token(refresh_token)` — live hot-swap, no restart
4. Redirect to `/`

### Dashboard auth indicator

A small status dot (green = healthy, red = auth_failed) rendered from an in-memory flag on `FamilyLinkService`. Shown in the dashboard header partial. No polling needed — just renders current state on each page load.

### Fallback B — iOS Shortcut (if PoC fails)

If the Bearer token PoC test returns 401/403, the 503 page instead shows:

> "To reconnect: open google.com on your phone, run [this Shortcut], and tap Send."

The Shortcut: opens google.com → runs `document.cookie.match(/SAPISID=([^;]+)/)[1]` → POSTs SAPISID value to `POST /admin/refresh-sapisid` (protected endpoint). The server rebuilds SAPISIDHASH auth from the new SAPISID.

---

## Section 3 — Health Check + Discord Alerting

### New background task: `health_check_loop`

Added to `main.py` lifespan alongside `poller_loop`. Runs every 30 minutes via `asyncio.sleep`.

```python
async def health_check_loop(service: FamilyLinkService, notifier: DiscordNotifier | None):
    _alert_active = False
    while True:
        await asyncio.sleep(1800)  # 30 min
        try:
            await service.get_members()
            if _alert_active:
                _alert_active = False
                await notifier.notify_session_restored()
        except (SessionExpiredError, Exception):
            if not _alert_active:
                _alert_active = True
                await notifier.notify_session_expired()
```

### Discord notifier additions (`services/discord_notifier.py`)

Two new methods on `DiscordNotifier`:

- `notify_session_expired()` — posts embed: "⚠️ Google session expired. Open the Family Link web UI to reconnect."
- `notify_session_restored()` — posts embed: "✅ Family Link session restored."

Both are no-ops when `self._channel is None` (Discord disabled), consistent with existing pattern.

### Linux machines during expiry

Hold last known state. The Linux poller already caches device state locally (SSH-based enforcement). No change needed — the poller continues operating on cached data when the Family Link API is unreachable.

---

## Section 4 — File Change Summary

| File | Change |
|---|---|
| `familylink/auth.py` | Add `OAuthResolver` class |
| `familylink/client.py` | `oauth_token` param; Bearer auth mode; no-op API key when using Bearer |
| `familylink_server/auth/oauth.py` | Add `/auth/reauth` route; extend callback to store refresh_token + call `reinit_with_token` |
| `familylink_server/services/family_link.py` | Token expiry check + auto-refresh; `reinit_with_token()`; `auth_failed` flag |
| `familylink_server/services/discord_notifier.py` | `notify_session_expired()`, `notify_session_restored()` |
| `familylink_server/main.py` | `health_check_loop` in lifespan; pass service to it; update 503 page HTML |
| `familylink_server/db/models.py` | Add `OAuthToken` model |
| `alembic/versions/` | New migration: create `oauth_tokens` table |
| `familylink_server/routers/dashboard.py` | Pass `auth_failed` flag to template context |
| `familylink_server/templates/` | 503 page: add Reconnect button; dashboard header: auth status dot |

**No new dependencies.** `httpx` (already present) handles token refresh calls.

**One Alembic migration** — creates `oauth_tokens` table.

---

## Fallback Plan

If Bearer token PoC fails (returns 401/403):

- Skip Sections 1 auth layer changes
- Keep `FamilyLinkService` cookie-based
- Keep `reinit_with_token` → replace with `reinit_with_cookies(b64_cookies: str)`
- Keep `/auth/reauth` route → replace with `/admin/refresh-sapisid` POST endpoint
- 503 page shows iOS Shortcut instructions instead of OAuth button
- Health check and Discord alerting remain unchanged

---

## Open Questions / Risks

| Risk | Mitigation |
|---|---|
| Bearer token PoC fails | Fallback plan above; iOS Shortcut covers mobile |
| Google revokes refresh_token (password change, security event) | Health check detects within 30 min; Discord alert; Reconnect button on 503 page |
| `oauth_tokens` migration fails on existing DB | Migration is additive (CREATE TABLE) — safe to run on live DB |
| `prompt=consent` not always issuing refresh_token | Use `include_granted_scopes=false` + `prompt=consent` together |
