# Server Deployment

### Prerequisites

- PostgreSQL database (Cloud SQL, Neon, AWS RDS, etc.)
- Google OAuth 2.0 credentials (see below)
- Deployment platform: Railway, Render, Fly.io, or similar

### Step 1: Create Google OAuth 2.0 credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Select your project (create one if needed)
3. Click **Create Credentials** > **OAuth 2.0 Client ID**
4. Choose **Web application**
5. Under **Authorized redirect URIs**, add your deployment URL:
   - Railway: `https://<your-app>.railway.app/auth/callback`
   - Render: `https://<your-app>.onrender.com/auth/callback`
   - Fly.io: `https://<your-app>.fly.dev/auth/callback`
   - Coolify: `https://<your-coolify-domain>/auth/callback`
6. Copy your **Client ID** and **Client Secret**

### Step 2: Export Family Link cookies

On your local machine:

```bash
# Export cookies and generate base64 string
familylink export-cookies --base64
```

This outputs both a `cookies.txt` file and a base64-encoded string. Copy the base64 string.

### Step 3: Set environment variables

In your deployment platform's dashboard, set these environment variables (see `.env.example` for details):

| Variable                    | Description                                                                                                                             |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`            | PostgreSQL connection string:`postgresql+asyncpg://user:password@host/dbname`                                                         |
| `SECRET_KEY`              | Random 32-byte hex (generate:`python -c "import secrets; print(secrets.token_hex(32))"`)                                              |
| `GOOGLE_CLIENT_ID`        | From Google OAuth credentials                                                                                                           |
| `GOOGLE_CLIENT_SECRET`    | From Google OAuth credentials                                                                                                           |
| `FAMILYLINK_GOOGLE_EMAIL` | Parent's Gmail address                                                                                                                  |
| `FAMILYLINK_COOKIES_B64`  | Base64 output from`familylink export-cookies --base64`                                                                                |
| `CACHE_TTL_SECONDS`       | Cache duration in seconds (default:`900`)                                                                                             |
| `DEBUG`                   | Set to`true` to disable `Secure` flag on the session cookie — required for local HTTP (see [development.md](development.md))       |
| `COOKIE_REFRESHER_URL`    | Internal URL of the cookie-refresher sidecar, e.g.`http://cookie-refresher:8080` — enables auto-refresh on session expiry (optional) |
| `REFRESHER_API_KEY`       | Shared secret sent as`X-Api-Key` to the sidecar — must match the sidecar's own `REFRESHER_API_KEY` (optional but recommended)      |
| `NTFY_TOPICS`             | Per-kid ntfy push topics:`child_id:topic,child_id:topic` — empty disables ntfy notifications (optional, see [ntfy.md](ntfy.md))    |
| `NTFY_BASE_URL`           | Base URL of the ntfy server (default:`http://ntfy-qs0o4os08kggkcgs4kos4sgk.192.168.0.22.sslip.io` — self-hosted intranet instance)   |
| `COOLIFY_URL`             | _(ops workstation only)_ Base URL of your Coolify instance — used by `export-cookies --coolify`                                    |
| `COOLIFY_TOKEN`           | _(ops workstation only)_ Coolify API token — used by `export-cookies --coolify`                                                    |
| `COOLIFY_APP_UUID`        | _(ops workstation only)_ UUID of the Coolify app to update — used by `export-cookies --coolify`                                    |

### Step 4: Run database migrations

Most platforms support a "release command" — set it to:

```bash
alembic upgrade head
```

This runs once per deployment before the web server starts.

### Step 5: Coolify deployment

Coolify uses Traefik as its reverse proxy, which terminates TLS and forwards requests to the container over plain HTTP internally. Without special configuration uvicorn would generate `http://` OAuth callback URLs, causing a `redirect_uri_mismatch` error from Google.

The `Dockerfile` `CMD` already includes the required flags:

```
--proxy-headers --forwarded-allow-ips='*'
```

This tells uvicorn to trust Traefik's `X-Forwarded-Proto: https` header so that `request.url_for()` generates `https://` URLs. The `*` is safe here because only Traefik can reach the container — it is not internet-exposed directly.

**Deployment steps:**

1. Create a new Coolify service from this repository (Docker Compose or Dockerfile).
2. Set all required environment variables in the Coolify service settings (see table above).
3. Register `https://<your-coolify-domain>/auth/callback` as an authorized redirect URI in Google Cloud Console.
4. Deploy. On first visit you will see `{"detail":"Not authenticated"}` — this is expected. Navigate to `/auth/login` to start the OAuth flow.

**Session resilience:** The server monitors the Family Link session in the background. A health check probe runs every 30 minutes; if it fails, the server sets an `auth_failed` flag and posts a Discord alert ("⚠️ Google session expired"). When the session is restored, another alert fires ("✅ Family Link session restored"). While `auth_failed` is set, a red banner appears on every page pointing at the sidecar retry / CLI re-export fallback (see below).

**Auto-refresh sidecar (recommended):** Two Docker services restore the session fully automatically — no human action required for routine refreshes. A persistent `firefox` container (headful, via noVNC) holds a real, continuously-logged-in parent Google session; the `cookie-refresher` sidecar reads that browser's *live* cookies on demand. Nothing is ever cloned or replayed, so there is no stale snapshot to go stale — the same reason a phone and a laptop can both stay signed into the same Google account for months without incident.

Google reliably blocks scripted username/password sign-in ("This browser or app may not be secure", regardless of IP or headless mode — a deliberate anti-automation policy). That's why the one-time login below is a real, human, headful sign-in through noVNC rather than anything automated.

```
════════════════════════════════════════════════════════════════════
 ONE-TIME (and rare re-auth) — YOU, via noVNC
════════════════════════════════════════════════════════════════════

  [1] Open the protected noVNC URL (FIREFOX_NOVNC_URL)
              │
              ▼
  [2] Sign into the parent Google account normally,
      inside that browser window
              │
              ▼
  [3] Session persists on the firefox_profile volume
      (cookies.sqlite) — nothing to bootstrap or upload
              │
              ▼
         ✅ done. The browser stays logged in and keeps
            itself warm; the refresher reads its cookies.

  You only repeat this if the session ever fully dies
  (password change, explicit sign-out, Google security
  event — rare).

════════════════════════════════════════════════════════════════════
 AUTOMATIC — the app handles this forever after, no human involved
════════════════════════════════════════════════════════════════════

  every 30 min: health_check_loop probes Family Link API
  every 12h:    proactive_refresh_loop rotates cookies early
              │
              ▼ (probe fails, or proactive timer fires)
  main app calls sidecar: POST /refresh
              │
              ▼
  sidecar reads the live firefox_profile's cookies.sqlite
  (browser_cookie3, no navigation, no snapshot)
  → verifies against the Family Link API
  → returns cookies_b64
              │
              ▼
  main app hot-reloads FamilyLinkService with fresh cookies
  Discord: "✅ restored" notification
              │
              ▼
         session working again, zero manual action

  ── if /refresh fails (profile never logged in, or the
     live session itself is dead) ──
              │
              ▼
  alert stays active, with exponential backoff → fallback:
    • sign back in via the noVNC UI (step [1]-[2] above), or
    • CLI: familylink export-cookies --coolify --restart
```

**Deploying the sidecar + browser in Coolify:**

1. Add a `firefox` service to your Coolify project using the `lscr.io/linuxserver/firefox` image (see `docker-compose.yml`). Mount a persistent volume at `/config` (this is `firefox_profile` — it holds the live, logged-in session; survives restarts/redeploys).
2. Put the `firefox` service's noVNC port (3000) behind authentication — see the security warning below — and note its URL.
3. Add a second service pointing at this repo with **Dockerfile** set to `Dockerfile.refresher`. Mount the same volume read-only at `/profile` and set `FIREFOX_PROFILE_DIR=/profile`.
4. Set the sidecar's environment variables:

   | Variable              | Description                                                                                          |
   | ---------------------- | ----------------------------------------------------------------------------------------------------- |
   | `REFRESHER_API_KEY` | Shared secret required as`X-Api-Key` on `/refresh`; protects the endpoint from other internal callers |

5. Note the sidecar's **internal** Coolify service URL (e.g. `http://cookie-refresher:8080`)
6. On the **main server** service, add:

   | Variable                 | Description                                                       |
   | ------------------------ | ------------------------------------------------------------------ |
   | `COOKIE_REFRESHER_URL` | Internal URL of the sidecar, e.g.`http://cookie-refresher:8080` |
   | `REFRESHER_API_KEY`    | Same value as set on the sidecar                                  |
   | `FIREFOX_NOVNC_URL`    | The protected noVNC URL from step 2 — linked from the session-expired page |

7. Deploy all three services, then open `FIREFOX_NOVNC_URL` and sign into the parent Google account once (see diagram above) — `/refresh` returns `409` until a session has been logged in at least once.
8. Smoke-test: `curl -X POST -H "X-Api-Key: <key>" http://<sidecar-internal>:8080/refresh` should return `{"cookies_b64": "..."}` within a few seconds.

> **No credentials handled by the sidecar.** The sidecar only reads cookies that are already live in the `firefox` container's profile — it never touches a Google password or TOTP secret. But that profile itself *is* an authenticated session; see the security warning below.

> **⚠️ Security warning — the `firefox` noVNC UI is equivalent to full control of the parent Google account.** Anyone who can reach it can act as the signed-in parent, and the `firefox_profile` volume stores live session tokens at rest (treat it like a credential store). This is a **larger exposure than a cookie snapshot**, so it MUST be locked down:
>
> - Put the noVNC route behind authentication (e.g. Traefik basic-auth) — never expose it publicly / unauthenticated on the internet.
> - Prefer keeping it internal-only and reaching it via an SSH tunnel rather than exposing any public URL at all.
> - `REFRESHER_API_KEY` still gates `/refresh`, but that's a separate, narrower control — it does not protect the noVNC UI itself.

**Refreshing cookies via CLI (requires restart):** When the sidecar isn't configured (or fails), re-export a full session from your local browser and push it to Coolify:

```bash
familylink export-cookies --browser chrome --base64 --coolify --restart
```

This exports cookies from Chrome, base64-encodes them, updates `FAMILYLINK_COOKIES_B64` in the Coolify app environment, and triggers a container restart — no manual copy-paste or dashboard visit required.

The following environment variables must be set in your **local** `.env` before running the command (they are not needed on the server):

| Variable             | Description                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------- |
| `COOLIFY_URL`      | Base URL of your Coolify instance, e.g.`http://192.168.0.22:8000`                       |
| `COOLIFY_TOKEN`    | Coolify API token — generate in Coolify → Security → API Tokens                        |
| `COOLIFY_APP_UUID` | UUID of the Coolify application to update — visible in the app's URL or General settings |

**Traefik labels** are already present in `docker-compose.yml` and configure:

- HTTP → HTTPS redirect
- TLS termination
- Gzip compression
- Port routing to the uvicorn process on `8000`

### Optional features

- [Linux machine management](linux-machines.md) — lock/power-off enforcement on a child's PC via SSH
- [eKRÉTA homework scraping](ekreta.md) — pull homework from the Hungarian eKRÉTA school system
- [Verifying ntfy setup](ntfy.md) — confirm push notifications reach each kid's phone
