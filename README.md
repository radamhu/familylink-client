# Family Link

A non-official Python package to interact with Google Family Link and linux machines, to manage your kids' screen time.

<p align="center">
  <img src="logo.jpeg" alt="Family Link logo" width="200" height="200">
</p>

## Prerequisites

1. Have a Google Family Link family set up (parent + child)
2. Be signed into Chrome or Firefox as the **parent** account
3. Visit **[https://familylink.google.com](https://familylink.google.com)** at least once in that browser (this establishes the necessary session)

## Three modes of operation

This project ships three independent ways to manage Family Link:

|                               | CLI                                          | Web server                                      | Discord bot                                              |
| ----------------------------- | -------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------- |
| **Config storage**      | `config.csv` (declarative, file-based)     | PostgreSQL (`app_configs` table)              | None (reads live from API)                               |
| **Workflow**            | Run as a cron job; pushes diffs to the API   | Interactive web UI; changes applied immediately | Slash commands in Discord; daily summary posted at night |
| **Auth**                | Browser cookies or`FAMILYLINK_COOKIES_B64` | Same cookie auth + Google OAuth login           | Same cookie auth; bot token via`DISCORD_BOT_TOKEN`     |
| **History / audit log** | None                                         | `usage_snapshots`, `audit_log` tables       | None (change notifications posted to a channel)          |
| **When to use**         | Scripted or headless enforcement             | Always-on dashboard with persistent history     | Quick checks and ad-hoc changes from a family Discord    |

If you run the server, you do not need `config.csv`. Limit rules are managed through the web UI and stored in the database. The only CLI commands that remain useful in a server deployment are `export-cookies` (to refresh the Google session) and `fetch-config` (to export current API state as a CSV snapshot).

### Usage as a Discord bot

The Discord bot runs as part of the server process when `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, and `DISCORD_CHANNEL_ID` are all set. It exposes slash commands for the configured guild:

| Command             | Description                                                                  |
| ------------------- | ---------------------------------------------------------------------------- |
| `/apps list`      | Paginated list of apps and their current state (blocked / limited / allowed) |
| `/apps limit`     | Set a daily time limit for an app                                            |
| `/apps block`     | Block an app for a child                                                     |
| `/apps allow`     | Always-allow an app for a child                                              |
| `/devices list`   | List devices and their lock state                                            |
| `/devices lock`   | Lock a supervised device                                                     |
| `/devices unlock` | Unlock a supervised device                                                   |
| `/usage today`    | Show today's top app usage for a child                                       |
| `/usage history`  | Show daily usage totals for the last N days                                  |
| `/status`         | Dashboard overview of all children and devices                               |
| `/refresh`        | Invalidate the in-memory cache                                               |

A daily usage summary is automatically posted to the configured channel at `DISCORD_SUMMARY_TIME` (default `20:00`). Only members with the `DISCORD_ALLOWED_ROLE` role (default `Parent`) can run commands.

### Linux machine management

The server can manage Linux machines (e.g. a child's gaming PC) via SSH. It polls each machine on a 60-second cycle, accumulates active graphical-session time, and enforces a daily quota by locking the screen and — after a grace period — powering the machine off.

The `/linux-machines` web page lets you add machines, view today's usage, grant bonus minutes, and trigger a lock or power-off immediately.

#### Requirements per managed machine

**OS note:** The SSH commands rely on systemd-logind and D-Bus. Tested on Bazzite (Fedora Atomic, KDE Plasma 6). Adjust if the target machine uses a different desktop environment.

**1. Generate an SSH key pair**

Use the *Generate key* button on the `/linux-machines` add/edit form. Copy the public key to the target machine:

```bash
# On the target machine (run once)
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo '<paste public key here>' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

**2. Allow passwordless poweroff via sudo**

`systemctl poweroff` requires polkit admin authentication, which is unavailable over a non-interactive SSH session. Add a narrow sudoers rule so the SSH user can power off without a password.

Run the following on the target machine (either physically or via `ssh -t`):

```bash
echo 'suriel ALL=(ALL) NOPASSWD: /usr/bin/systemctl poweroff' | sudo tee /etc/sudoers.d/familylink-poweroff
sudo chmod 440 /etc/sudoers.d/familylink-poweroff
# Verify syntax before relying on it
sudo visudo -c -f /etc/sudoers.d/familylink-poweroff
```

Replace `suriel` with the actual SSH user configured for that machine.

> A helper script at `~/familylink-setup.sh` is written to the target machine during first-time setup and performs these three commands automatically — just run `sudo bash ~/familylink-setup.sh` once from a privileged terminal.

#### How enforcement works

| Condition                                      | Action                                                       |
| ---------------------------------------------- | ------------------------------------------------------------ |
| Active graphical session (seat-based) detected | Accumulate seconds toward the daily quota                    |
| Quota exceeded, not yet locked                 | Lock screen via D-Bus (`org.freedesktop.ScreenSaver.Lock`) |
| Locked, grace period elapsed                   | Power off via`sudo systemctl poweroff`                     |
| Bonus minutes granted while locked             | Kill`kscreenlocker_greet` to dismiss the lock screen       |

The daily quota and grace period (default 5 min) are configurable per machine.

### Usage as a CLI

Create a `config.csv` file with the following format:

```csv
App,Max Duration,Days,Time Ranges
Calculator,,,                       # always allowed
Youtube,0:10,Mon-Fri,               # 10 minutes per day during weekdays
Youtube,0:30,Sat-Sun,               # 30 minutes per day on weekends
Fortnite,1:00,Wed,13:00-18:00       # 1 hour on Wednesday, between 13:00 and 18:00
Fortnite,1:00,Sat-Sun,09:30-18:00   # 1 hour on weekends, between 09:30 and 18:00
Google Photos,0:10,,                # 10 minutes everyday
```

Apps not in the list will be blocked.

```bash
familylink --dry-run config.csv                                    # Preview changes without applying
familylink config.csv                                               # Apply changes
familylink --browser chrome config.csv                             # Use Chrome instead of Firefox
familylink export-cookies --base64                                  # Export cookies for cloud deployment
familylink export-cookies --browser chrome                         # Export from Chrome, write cookies.txt
familylink export-cookies --base64 --coolify                       # Export and sync to Coolify
familylink export-cookies --base64 --coolify --restart             # Export, sync to Coolify, restart app
```

The `familylink` command and the `export-cookies` subcommand support the following flags (`export-cookies`-only flags are noted):

| Flag                   | Description                                                                                                                                                                                          |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--dry-run`          | Print what would be done without making changes                                                                                                                                                      |
| `--browser`          | `firefox` (default) or `chrome`                                                                                                                                                                  |
| `--cookie-file`      | Path to a Netscape-format cookies file                                                                                                                                                               |
| `-v` / `--verbose` | Enable debug logging                                                                                                                                                                                 |
| `--output` / `-o`  | Output file path (default:`cookies.txt`) — `export-cookies` only                                                                                                                                |
| `--base64`           | Also print the base64 value for`FAMILYLINK_COOKIES_B64` and update `.env` — `export-cookies` only                                                                                             |
| `--coolify`          | Push`FAMILYLINK_COOKIES_B64` to the Coolify app after updating `.env`. Requires `--base64`. Reads `COOLIFY_URL`, `COOLIFY_TOKEN`, `COOLIFY_APP_UUID` from env — `export-cookies` only |
| `--restart`          | Restart the Coolify app after pushing the env var. Requires`--coolify` — `export-cookies` only                                                                                                  |

## Development setup

### Prerequisites

- **Python 3.12** — via [`pyenv`](https://github.com/pyenv/pyenv) (install: `brew install pyenv`)
- **[direnv](https://direnv.net/)** — auto-loads the virtualenv (install: `brew install direnv`)

### Quick start

```bash
# 1. Clone & enter the repo
git clone <repo-url>
cd familylink-client

# 2. Create .env from example (edit with your secrets)
cp .env.example .env

# 3. Install Python 3.12 via pyenv (if not already installed)
pyenv install 3.12

# 4. Set local Python version (creates .python-version)
pyenv local 3.12

# 5. Create virtualenv with a friendly name (creates .venv/)
python -m venv .venv --prompt familylink-client

# 6. Activate & install dependencies
source .venv/bin/activate
pip install -e ".[dev,test]"  # install package + dev/test tools (pytest, ruff, mypy, pre-commit...)

# 7. Allow direnv — auto-activates .venv + sets PYTHONPATH=src + loads .env on cd
direnv allow

# 8. (Optional) Install pre-commit hooks (runs ruff, ruff-format, etc. before each commit)
pre-commit install
```

> **Note:** `direnv allow` re-activates the venv whenever you `cd` into the project.

### Makefile

Common development tasks are available via `make`:

**Local development**

| Command              | When to use                                                                        |
| -------------------- | ---------------------------------------------------------------------------------- |
| `make install`     | First-time setup — creates`.venv`, installs all deps and pre-commit hooks       |
| `make dev`         | Start the uvicorn dev server locally with hot reload (`http://localhost:8000`)   |
| `make migrate`     | After pulling changes that add Alembic migrations — applies them to your local DB |
| `make test`        | Run the full test suite before committing                                          |
| `make test-unit`   | Fast feedback loop — unit tests only, no DB required                              |
| `make test-server` | Server/integration tests (requires DB env vars from`.env`)                       |
| `make lint`        | Check code style without changing files                                            |
| `make lint-fix`    | Auto-fix lint issues in place                                                      |
| `make format`      | Format all source files with ruff                                                  |
| `make typecheck`   | Run mypy static type checking                                                      |
| `make clean`       | Wipe`.venv`, caches, and build artifacts for a clean slate                       |

**Docker (local stack)**

| Command                  | When to use                                                                                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make docker-up`       | Start the stack (db + web) using the**current image** — use when the image is already up to date and you just need the containers running     |
| `make docker-deploy`   | **Standard deploy** — refreshes cookies in `.env`, rebuilds the `web` image, and restarts the container; run this after every code change |
| `make docker-restart`  | Same as`docker-deploy`; prefer `docker-deploy` for clarity                                                                                       |
| `make docker-build`    | Refresh cookies and rebuild the`web` image without restarting (pre-warm before `docker-up`)                                                      |
| `make refresh-cookies` | Manually refresh`FAMILYLINK_COOKIES_B64` in `.env` from Chrome without rebuilding — useful when only the session has expired                    |
| `make docker-down`     | Stop all services cleanly                                                                                                                            |
| `make docker-logs`     | Tail live logs from all services                                                                                                                     |
| `make docker-clean`    | Stop services and delete containers + volumes (resets the database)                                                                                  |
| `make docker-purge`    | Nuclear option — removes all images, volumes, and Docker cache                                                                                      |

> **Cookie refresh:** `docker-deploy`, `docker-restart`, and `docker-build` all automatically run
> `familylink export-cookies --browser chrome --base64` first, which updates `FAMILYLINK_COOKIES_B64`
> in `.env`. Google sessions expire on sign-out or password change — the rebuild step ensures
> the container always starts with a fresh cookie.
>
> **Important:** `docker-up` alone does **not** refresh cookies or rebuild the image.
> Always run `make docker-deploy` after code changes or when the session may have expired.

Quick start with Makefile:

```bash
make install
direnv allow
```

### Codebase navigation

A knowledge graph (`graphify-out/graph.json`) is checked in. Use it to orient yourself before reading source files:

```bash
# Install graphify once
pip install graphifyy

# Then query the graph
graphify query "<question>"
graphify explain "<concept>"
graphify path "<NodeA>" "<NodeB>"
```

**Architecture questions**

```bash
graphify query "Why does FamilyLinkService bridge Discord commands to 17 different communities?"
graphify query "How does FamilyLink connect the API client to the CLI, server, and Discord bot?"
graphify query "Why does DiscordNotifier connect app management to session alert tests?"
```

**Auth and session questions**

```bash
graphify query "How does CookieResolver pick between browser cookies, FAMILYLINK_COOKIES_B64, and SAPISID?"
graphify query "What happens when a Google session expires — which code paths handle auth_failed?"
graphify query "How does cookie hot-reload work without a container restart?"
graphify path "CookieResolver" "FamilyLinkService"
```

**HTMX and server questions**

```bash
graphify query "How do HTMX mutation endpoints return partials — which templates are involved?"
graphify query "What does the lifespan startup sequence initialise and in what order?"
graphify path "lifespan()" "FamilyLinkService"
graphify explain "HTMX Mutation Endpoint Returning HTML Partials"
```

**Discord bot questions**

```bash
graphify query "How do Discord slash commands reach FamilyLinkService?"
graphify query "What is the relationship between FamilyLinkBot, AppsGroup, and DiscordNotifier?"
graphify query "How does the daily summary get posted to Discord?"
```

**Linux machine questions**

```bash
graphify query "How does poll_machine enforce daily screen time quotas?"
graphify query "What triggers a lock vs a power-off on a Linux machine?"
graphify path "poll_machine()" "LinuxUsageSnapshot"
```

**Data flow questions**

```bash
graphify query "How do positional JSON arrays from the Google API become Pydantic models?"
graphify path "parse_apps_and_usage()" "AppUsage"
graphify query "How does get_service() inject FamilyLinkService into route handlers?"
```

**Testing questions**

```bash
graphify query "Which tests cover the cookie hot-reload endpoint?"
graphify query "How are Discord bot commands tested without a real Discord connection?"
graphify query "What does the server test conftest set up?"
```

### Docker development

Running the server locally via `docker compose up` requires two extra steps because Google OAuth sets a `Secure` session cookie that browsers silently drop over plain HTTP.

**1. Add `DEBUG=true` to your `.env`**

```
DEBUG=true
```

This disables the `Secure` flag on the `fl_session` cookie so it works over `http://localhost`.
Never set this in production — without `Secure`, the cookie can be sent over unencrypted connections.

**2. Register the local redirect URI in Google Cloud Console**

Go to [APIs &amp; Services → Credentials](https://console.cloud.google.com/apis/credentials), edit your OAuth 2.0 Client ID, and add the following under **Authorized redirect URIs**:

```
http://localhost:8000/auth/callback
```

Then start the stack (this also refreshes your Google session cookies automatically):

```bash
make docker-deploy
```

The app will be available at `http://localhost:8000`.

> If your Google session expires later (sign-out, password change), run `make docker-deploy` again
> or `make refresh-cookies` if you only need to update the cookie without a full rebuild.

**Authentication flow:**

1. Open **http://localhost:8000/auth/login** in your browser
2. You'll be redirected to Google's OAuth consent screen — sign in with the parent Google account matching `FAMILYLINK_GOOGLE_EMAIL`
3. After authorizing, Google redirects back to `/auth/callback`; the server verifies the email and sets a session cookie (`fl_session`)
4. You're redirected to the home page — you're now authenticated

If you see a `401` error at `http://localhost:8000/`, you haven't logged in yet — just go to `/auth/login`.

## Server Deployment

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
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`            | PostgreSQL connection string:`postgresql+asyncpg://user:password@host/dbname`                                                         |
| `SECRET_KEY`              | Random 32-byte hex (generate:`python -c "import secrets; print(secrets.token_hex(32))"`)                                              |
| `GOOGLE_CLIENT_ID`        | From Google OAuth credentials                                                                                                           |
| `GOOGLE_CLIENT_SECRET`    | From Google OAuth credentials                                                                                                           |
| `FAMILYLINK_GOOGLE_EMAIL` | Parent's Gmail address                                                                                                                  |
| `FAMILYLINK_COOKIES_B64`  | Base64 output from`familylink export-cookies --base64`                                                                                |
| `CACHE_TTL_SECONDS`       | Cache duration in seconds (default:`900`)                                                                                             |
| `DEBUG`                   | Set to`true` to disable `Secure` flag on the session cookie — required for local HTTP (see below)                                  |
| `COOKIE_REFRESHER_URL`    | Internal URL of the cookie-refresher sidecar, e.g.`http://cookie-refresher:8080` — enables auto-refresh on session expiry (optional) |
| `REFRESHER_API_KEY`       | Shared secret sent as`X-Api-Key` to the sidecar — must match the sidecar's own `REFRESHER_API_KEY` (optional but recommended)      |
| `COOLIFY_URL`             | _(ops workstation only)_ Base URL of your Coolify instance — used by `export-cookies --coolify`                                    |
| `COOLIFY_TOKEN`           | _(ops workstation only)_ Coolify API token — used by `export-cookies --coolify`                                                    |
| `COOLIFY_APP_UUID`        | _(ops workstation only)_ UUID of the Coolify app to update — used by `export-cookies --coolify`                                    |

### Step 4: Run database migrations

Most platforms support a "release command" — set it to:

```bash
alembic upgrade head
```

This runs once per deployment before the web server starts.

### Step 5: Deploy

Ensure your `Procfile` is committed (created in Step 1):

```
web: uvicorn familylink_server.main:app --host 0.0.0.0 --port $PORT
```

Your platform will read this and start the server on the port it provides via the `$PORT` environment variable.

#### Coolify deployment

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

**Auto-refresh sidecar (recommended):** A separate Docker service (`cookie-refresher`) can restore the session fully automatically — no human action required for routine refreshes. It does **not** automate a Google login (Google reliably blocks scripted username/password sign-in with "This browser or app may not be secure", regardless of IP or headless mode — this is a deliberate anti-automation policy, not a bug to work around). Instead, it replays a real, human-authenticated session that you bootstrap once from your own browser.

```
════════════════════════════════════════════════════════════════════
 ONE-TIME (and rare re-auth) — YOU, on your laptop
════════════════════════════════════════════════════════════════════

  [1] Log into Google normally
      in your real Chrome
              │
              ▼
  [2] Run scripts/bootstrap_refresher_session.py
      → pulls cookies from that Chrome
        (browser_cookie3, same lib the CLI
         export-cookies already uses)
      → converts to Playwright storage_state JSON
      → POSTs it to the deployed web app
              │
              ▼
  [3] web app: POST /admin/refresher-bootstrap
      (X-Api-Key auth)
      → proxies body to sidecar's internal /bootstrap
              │
              ▼
  [4] sidecar: POST /bootstrap
      → writes state.json to its Docker volume
              │
              ▼
         ✅ done. No automated login ever happens —
            nothing for Google to flag.

  You only repeat this if the persisted session ever
  fully dies (password change, long inactivity,
  Google security event — rare).

════════════════════════════════════════════════════════════════════
 AUTOMATIC — the app handles this forever after, no human involved
════════════════════════════════════════════════════════════════════

  every 30 min: health_check_loop probes Family Link API
              │
              ▼ (probe fails: SessionExpiredError)
  main app calls sidecar: POST /refresh
              │
              ▼
  sidecar loads state.json from volume into Playwright
  → visits myaccount.google.com (no login form touched)
  → grabs fresh cookies
  → writes rotated cookies BACK to state.json
  → returns cookies_b64
              │
              ▼
  main app hot-reloads FamilyLinkService with fresh cookies
  Discord: "✅ restored" notification
              │
              ▼
         session working again, zero manual action

  ── if /refresh fails (state.json missing, or Google shows
     no SAPISID after nav = persisted session is fully dead) ──
              │
              ▼
  alert stays active → same existing fallback:
    • re-run bootstrap script (step [1]-[4] above), or
    • CLI: familylink export-cookies --coolify --restart
```

**Deploying the sidecar in Coolify:**

1. Add a second service to your Coolify project pointing at the same repo, but set **Dockerfile** to `Dockerfile.refresher`
2. Mount a persistent volume into the sidecar at `/data` (holds the bootstrapped session; survives container restarts/redeploys)
3. Set the sidecar's environment variables:

   | Variable             | Description                                                                                                     |
   | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
   | `REFRESHER_API_KEY` | Shared secret required as `X-Api-Key` on both `/refresh` and `/bootstrap`; protects the endpoints from other internal callers |

4. Note the sidecar's **internal** Coolify service URL (e.g. `http://cookie-refresher:8080`)
5. On the **main server** service, add:

   | Variable                 | Description                                                       |
   | ------------------------ | ----------------------------------------------------------------- |
   | `COOKIE_REFRESHER_URL` | Internal URL of the sidecar, e.g. `http://cookie-refresher:8080` |
   | `REFRESHER_API_KEY`    | Same value as set on the sidecar                                  |

6. Deploy both services, then run `WEB_BASE_URL=https://<your-coolify-domain> REFRESHER_API_KEY=<value from Coolify env> scripts/bootstrap_refresher_session.py` from your laptop (see diagram above) to seed the sidecar's persisted session — `/refresh` returns 400 until this has been done at least once.
7. Smoke-test: `curl -X POST -H "X-Api-Key: <key>" http://<sidecar-internal>:8080/refresh` should return `{"cookies_b64": "..."}` within ~30 seconds.

> **No credentials on the sidecar.** Because bootstrap captures an already-authenticated session from your real browser, the sidecar never sees your Google password or TOTP secret — nothing to leak, nothing for Google's automated-login detector to catch.

**Refreshing cookies via CLI (requires restart):** When the sidecar isn't configured (or fails), re-export a full session from your local browser and push it to Coolify:

```bash
familylink export-cookies --browser chrome --base64 --coolify --restart
```

This exports cookies from Chrome, base64-encodes them, updates `FAMILYLINK_COOKIES_B64` in the Coolify app environment, and triggers a container restart — no manual copy-paste or dashboard visit required.

The following environment variables must be set in your **local** `.env` before running the command (they are not needed on the server):

| Variable             | Description                                                                               |
| -------------------- | ----------------------------------------------------------------------------------------- |
| `COOLIFY_URL`      | Base URL of your Coolify instance, e.g.`http://192.168.0.22:8000`                       |
| `COOLIFY_TOKEN`    | Coolify API token — generate in Coolify → Security → API Tokens                        |
| `COOLIFY_APP_UUID` | UUID of the Coolify application to update — visible in the app's URL or General settings |

**Traefik labels** are already present in `docker-compose.yml` and configure:

- HTTP → HTTPS redirect
- TLS termination
- Gzip compression
- Port routing to the uvicorn process on `8000`

### Troubleshooting

- **Database connection fails**: Verify `DATABASE_URL` format and that your database is reachable from the deployment platform
- **"Could not find SAPISID" / 503 "Google session expired"**: The cookies have expired. If the `cookie-refresher` sidecar is configured, it retries automatically on the next health check. Otherwise re-run `familylink export-cookies --base64 --coolify --restart` from a machine signed into the parent account
- **OAuth redirect fails / `redirect_uri_mismatch`**: Check that the redirect URI in Google Cloud Console exactly matches your deployed URL (scheme included — `https://` not `http://`)
- **Behind a reverse proxy, OAuth callback URL is `http://` instead of `https://`**: The app must run with `--proxy-headers --forwarded-allow-ips='*'` so uvicorn trusts the `X-Forwarded-Proto` header from the proxy. This is already set in the `Dockerfile` `CMD`. If deploying via `Procfile` or another mechanism, add the flags there too.
- **`{"detail":"Not authenticated"}` on first visit**: You haven't logged in yet — navigate to `/auth/login`
- **Login succeeds but every page redirects back to `/auth/login`**: The session cookie is being dropped. If running locally over HTTP, set `DEBUG=true` in `.env` (see above)
