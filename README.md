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
3. Set the sidecar's environment variables:| Variable              | Description                                                                                                                        |
   | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
   | `REFRESHER_API_KEY` | Shared secret required as`X-Api-Key` on both `/refresh` and `/bootstrap`; protects the endpoints from other internal callers |
4. Note the sidecar's **internal** Coolify service URL (e.g. `http://cookie-refresher:8080`)
5. On the **main server** service, add:| Variable                 | Description                                                       |
   | ------------------------ | ----------------------------------------------------------------- |
   | `COOKIE_REFRESHER_URL` | Internal URL of the sidecar, e.g.`http://cookie-refresher:8080` |
   | `REFRESHER_API_KEY`    | Same value as set on the sidecar                                  |
6. Deploy both services, then run
7. ```Shell
   WEB_BASE_URL="WEB_BASE_URL" REFRESHER_API_KEY="WEBBASEURL"REFRESHERAPIKEY="REFRESHER_API_KEY" REFRESHER_INSECURE_SKIP_TLS_VERIFY="$REFRESHER_INSECURE_SKIP_TLS_VERIFY" python scripts/bootstrap_refresher_session.py --browser chrome
   ```
8. from your laptop (see diagram above) to seed the sidecar's persisted session — `/refresh` returns 400 until this has been done at least once.
9. Smoke-test: `curl -X POST -H "X-Api-Key: <key>" http://<sidecar-internal>:8080/refresh` should return `{"cookies_b64": "..."}` within ~30 seconds.

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

**Refreshing cookies from the parent's Android phone (bookmarklet):** when there's no laptop handy, a `javascript:` bookmarklet tapped from the phone's own Chrome bookmarks can relay a fresh `SAPISID` cookie to the app and reconnect it in-process — no restart, no desktop browser.

One-time setup:

1. Generate a token and set it on the server: `python -c "import secrets; print(secrets.token_hex(32))"` → set as `SAPISID_RELAY_TOKEN` in the server's environment, then restart the server.
2. Build the bookmarklet URL, substituting your app's base URL and the token you just generated:

   ```
   javascript:(function(){var m=document.cookie.match(/(?:^|; )SAPISID=([^;]+)/);if(!m){alert('Not signed into Google in this tab.');return;}var w=window.open('','sapisid-relay-target');var f=document.createElement('form');f.method='POST';f.action='https://YOUR-APP-BASE-URL/admin/sapisid-relay';f.target='sapisid-relay-target';var i1=document.createElement('input');i1.name='sapisid';i1.value=decodeURIComponent(m[1]);f.appendChild(i1);var i2=document.createElement('input');i2.name='token';i2.value='YOUR-TOKEN';f.appendChild(i2);document.body.appendChild(f);f.submit();})();
   ```
3. On a desktop Chrome signed into the **same Google account** as the parent's phone, save that URL as a bookmark (e.g. name it "Refresh FamilyLink"). Chrome's bookmark sync carries it to the phone's Chrome automatically.
4. On the phone, confirm the bookmark appears (Chrome menu → Bookmarks).

Each time a refresh is needed:

1. On the phone, open any signed-in Google page in Chrome (e.g. `myaccount.google.com`).
2. Open the bookmark. A new tab shows "Reconnected." on success. (If nothing seems to happen, check for a new *background* tab — some Android Chrome versions open it without switching focus.)

This only refreshes from the *current* browser session — if Google has fully signed the account out, sign back in normally in Chrome first, then tap the bookmark.

**Traefik labels** are already present in `docker-compose.yml` and configure:

- HTTP → HTTPS redirect
- TLS termination
- Gzip compression
- Port routing to the uvicorn process on `8000`

### Troubleshooting (auth)

There are two separate auth layers, and they fail independently:

- **Google/Family Link session** — the cookies the server uses to call the Family Link API. Expires on sign-out, password change, or Google security events.
- **OAuth login** — your own login to *this app* (`fl_session` cookie). Separate from the above; only affects who can access the UI.

#### Google/Family Link session problems

| Symptom                                                                                | Command                                                                                                           | When                                                                                                                                                                     |
| -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 503 "Google session expired" page,`cookie-refresher` sidecar **is** configured | None — wait. The page itself triggers a background refresh; the 30-min health check retries too.                 | First response. Reload after ~1 minute.                                                                                                                                  |
| Sidecar logs show`Refresh failed: ... verification: HTTP 401` repeatedly             | `WEB_BASE_URL=<app-url> REFRESHER_API_KEY=<key> python scripts/bootstrap_refresher_session.py --browser chrome` | The sidecar's persisted session itself has died (rare: password change, long inactivity, security event). Run from a machine with Chrome logged into the parent account. |
| No sidecar configured, or above bootstrap didn't fix it                                | `familylink export-cookies --browser chrome --base64 --coolify --restart`                                       | Full manual reset. Requires restart. Works regardless of sidecar state.                                                                                                  |
| Just want to check current cookie validity without restarting anything                 | `familylink export-cookies --base64` (no `--coolify`)                                                         | Dry check — writes`cookies.txt` + prints base64, doesn't touch the deployment.                                                                                        |

The sidecar and `bootstrap_refresher_session.py` don't replace `export-cookies` — they automate the *recurring* refresh so you don't have to run `export-cookies` every few weeks. `bootstrap_refresher_session.py` only re-seeds the sidecar's stored session; it doesn't touch the running app's cookies directly. `export-cookies --coolify --restart` is the one command that always works, sidecar or not, because it pushes straight to the app.

#### App login (OAuth) problems

- **`{"detail":"Not authenticated"}` on first visit**: expected — navigate to `/auth/login`
- **OAuth redirect fails / `redirect_uri_mismatch`**: redirect URI in Google Cloud Console must exactly match your deployed URL, scheme included (`https://` not `http://`)
- **Behind a reverse proxy, callback URL comes back `http://` instead of `https://`**: app needs `--proxy-headers --forwarded-allow-ips='*'` so uvicorn trusts `X-Forwarded-Proto`. Already set in the `Dockerfile` `CMD` — add it manually if deploying via `Procfile` or another mechanism
- **Login succeeds but every page redirects back to `/auth/login`**: session cookie is being dropped — if running locally over HTTP, set `DEBUG=true` in `.env`

#### Auth & session endpoint reference

Every endpoint and command that touches a Google/session cookie, in one place.

Four paths keep the Google session alive: bootstrap once by hand, an automatic loop that runs forever, a manual CLI fallback, and a phone-only bookmarklet relay.

`familylink export-cookies --browser chrome --base64 --coolify --restart` and `python scripts/bootstrap_refresher_session.py --browser chrome` look similar but push to different places with different tokens — neither touches or generates a `SAPISID_RELAY_TOKEN`:

- `export-cookies` reads the full cookie jar from local Chrome, base64-encodes it, and (with `--coolify`) pushes `FAMILYLINK_COOKIES_B64` straight to the Coolify app's env vars, then restarts the container. No token beyond `COOLIFY_TOKEN` (Coolify's own API auth) is involved.
- `bootstrap_refresher_session.py` also reads the full cookie jar from local Chrome, but converts it to a Playwright `storage_state` and POSTs it to `/admin/refresher-bootstrap`, authenticated with `REFRESHER_API_KEY`, which proxies to the sidecar's `/bootstrap` — no Coolify involved, no restart.

Three separate, non-overlapping tokens exist in this codebase:

| Token                   | Set where        | Used by                            | Uploads                                                   |
| ----------------------- | ---------------- | ---------------------------------- | --------------------------------------------------------- |
| none (raw cookies)      | —               | `export-cookies --coolify`       | `FAMILYLINK_COOKIES_B64` → Coolify env                 |
| `REFRESHER_API_KEY`   | server + sidecar | `bootstrap_refresher_session.py` | full cookie jar → sidecar's`/bootstrap`                |
| `SAPISID_RELAY_TOKEN` | server only      | Android bookmarklet                | bare`SAPISID` string → in-process hot-swap, no restart |

```mermaid
sequenceDiagram
    actor Op as Operator (laptop)
    actor Parent as Parent (phone)
    participant Chrome as Real Chrome
    participant Script as bootstrap_refresher_session.py
    participant Main as Main App
    participant Side as Cookie-Refresher Sidecar
    participant GA as myaccount.google.com
    participant FL as kidsmanagement-pa (Family Link API)

    rect rgb(44,36,22)
    Note over Op,Side: BOOTSTRAP — one-time, or after password change / long inactivity
    Op->>Chrome: sign in normally
    Op->>Script: run bootstrap_refresher_session.py
    Script->>Chrome: browser_cookie3 → extract google.com cookies
    Script->>Main: POST /admin/refresher-bootstrap  (X-Api-Key)
    Main->>Side: proxy → POST /bootstrap
    Side->>Side: write state.json to volume
    end

    rect rgb(20,42,36)
    Note over Main,FL: AUTOMATIC — health_check_loop, every 30 min, no human involved
    loop every 1800s
        Main->>FL: get_members()  (probe)
        alt SessionExpiredError (401 / 403)
            Main->>Side: POST /refresh
            Side->>Side: load state.json into headless Chromium
            Side->>GA: goto https://myaccount.google.com/
            GA-->>Side: cookie jar (check: SAPISID present?)
            Side->>FL: verify get_members() with fresh cookies
            FL-->>Side: 200 OK
            Side->>Side: rewrite state.json (rotated cookies)
            Side-->>Main: { cookies_b64 }
            Main->>Main: hot-reload FamilyLinkService
        end
    end
    end

    rect rgb(48,26,28)
    Note over Op,Main: MANUAL FALLBACK — no SAPISID after nav = sidecar session is dead
    Op->>Chrome: sign in
    Op->>Op: familylink export-cookies --browser chrome --base64 --coolify --restart
    Op->>Main: push FAMILYLINK_COOKIES_B64 → env, restart container
    end

    rect rgb(30,30,50)
    Note over Parent,Main: ANDROID BOOKMARKLET — no laptop needed, no restart
    Parent->>Parent: open myaccount.google.com in phone Chrome (already signed in)
    Parent->>Parent: tap synced bookmarklet
    Note right of Parent: reads SAPISID from document.cookie
    Parent->>Main: POST /admin/sapisid-relay (sapisid, token)  [plain form, no CORS]
    Main->>Main: verify token (SAPISID_RELAY_TOKEN, compare_digest)
    Main->>Main: reinit_with_sapisid() → hot-swap client
    Main->>FL: get_members() (verify before reporting success)
    FL-->>Main: 200 OK
    Main-->>Parent: new tab: "Reconnected."
    end
```

| Endpoint / command                                                                                              | What it does                                                                                                                                                                                                                                                                                 | Google URL called                                                                                                                                                                                                                                                                                                 | Cookies stored where                                                                                                                                                                                                       | Local command / script                                                                                                                                                                                                              |
| --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /auth/login` ([oauth.py:54](src/familylink_server/auth/oauth.py#L54))                                     | Redirects browser into Google's OAuth consent screen for**app login** (not Family Link session)                                                                                                                                                                                        | `accounts.google.com` (OIDC discovery via `.well-known/openid-configuration`, [oauth.py:17](src/familylink_server/auth/oauth.py#L17))                                                                                                                                                                          | N/A — no cookie yet                                                                                                                                                                                                       | Browser navigation only                                                                                                                                                                                                             |
| `GET /auth/callback` ([oauth.py:61](src/familylink_server/auth/oauth.py#L61))                                  | Exchanges OAuth code, checks email ==`FAMILYLINK_GOOGLE_EMAIL`, sets app session cookie                                                                                                                                                                                                    | Google OAuth token endpoint (via authlib)                                                                                                                                                                                                                                                                         | Sets`fl_session` cookie (signed, httponly, 30-day `max_age`) in the browser — **not** a Google cookie, just this app's login                                                                                    | N/A                                                                                                                                                                                                                                 |
| `GET /auth/logout` ([oauth.py:81](src/familylink_server/auth/oauth.py#L81))                                    | Clears`fl_session`                                                                                                                                                                                                                                                                         | none                                                                                                                                                                                                                                                                                                              | Deletes`fl_session` cookie in browser                                                                                                                                                                                    | N/A                                                                                                                                                                                                                                 |
| `POST /admin/refresher-bootstrap` ([admin.py:15](src/familylink_server/routers/admin.py#L15))                  | Main app proxy: forwards a Playwright`storage_state` JSON to the sidecar's `/bootstrap`, protected by `X-Api-Key`                                                                                                                                                                      | none directly (pure proxy)                                                                                                                                                                                                                                                                                        | Passes through to sidecar; sidecar writes to`STATE_PATH` (default `/data/state.json`) on its Docker volume                                                                                                             | `scripts/bootstrap_refresher_session.py` (this is what calls it)                                                                                                                                                                  |
| `POST /bootstrap` on sidecar ([cookie_refresher_app.py:45](src/familylink_server/cookie_refresher_app.py#L45)) | Persists the uploaded`storage_state` JSON to disk for `/refresh` to reuse                                                                                                                                                                                                                | none                                                                                                                                                                                                                                                                                                              | Writes full cookie jar to`STATE_PATH` (default `/data/state.json`)                                                                                                                                                     | Called by`/admin/refresher-bootstrap` above, never directly                                                                                                                                                                       |
| `POST /refresh` on sidecar ([cookie_refresher_app.py:139](src/familylink_server/cookie_refresher_app.py#L139)) | Loads persisted`state.json` into headless Playwright Chromium, navigates to re-mint short-lived tokens, re-verifies against Family Link API, writes rotated cookies back                                                                                                                   | `https://myaccount.google.com/` ([cookie_refresher_app.py:84](src/familylink_server/cookie_refresher_app.py#L84)), then verifies against `https://kidsmanagement-pa.clients6.google.com` via `FamilyLink().get_members()` ([cookie_refresher_app.py:125](src/familylink_server/cookie_refresher_app.py#L125)) | Reads + rewrites`STATE_PATH` (`/data/state.json`) on sidecar volume                                                                                                                                                    | Called automatically by main app's`health_check_loop` / `_try_auto_refresh` ([main.py:71](src/familylink_server/main.py#L71)); can smoke-test manually with `curl -X POST -H "X-Api-Key: <key>" http://<sidecar>:8080/refresh` |
| Family Link API calls (e.g.`get_members`) ([client.py:35](src/familylink/client.py#L35))                       | Actual product API — apps, devices, usage, limits                                                                                                                                                                                                                                           | `https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1`                                                                                                                                                                                                                                               | Reads cookies resolved by`CookieResolver` — see priority list below                                                                                                                                                     | n/a (library-internal); CLI entry point is`familylink` main command                                                                                                                                                               |
| `CookieResolver.resolve()` ([auth.py:39](src/familylink/auth.py#L39))                                          | Resolves SAPISID + cookie jar the client authenticates with, first match wins:`FAMILYLINK_COOKIES_B64` → `FAMILYLINK_SAPISID` → `FAMILYLINK_COOKIE_FILE` → `./cookies.txt` (`browser="txt"`) → per-profile `sapisid.txt`/`cookies.txt` → `browser_cookie3` (host only)  | none itself — consumed by`client.py` calls above                                                                                                                                                                                                                                                               | Depends on source: env var (b64/plain), or local`cookies.txt` / `sapisid.txt` file, or live browser cookie store                                                                                                       | n/a — internal to every`familylink`/`familylink_server` auth path                                                                                                                                                              |
| `familylink export-cookies` ([cli.py:99](src/familylink/cli.py#L99))                                           | Pulls Google cookies straight from local Chrome/Firefox, filters to`google.com`, verifies `SAPISID` present, writes Netscape file, optionally base64-encodes + pushes to Coolify env + restarts                                                                                          | none (local browser cookie store only, via`browser_cookie3`)                                                                                                                                                                                                                                                    | Writes`cookies.txt` (or `--output` path) locally; with `--base64` also prints/writes `FAMILYLINK_COOKIES_B64` value to local `.env`; with `--coolify` pushes that value into the remote Coolify app's env vars | `familylink export-cookies --browser chrome --base64 [--coolify --restart]`                                                                                                                                                       |
| `scripts/bootstrap_refresher_session.py`                                                                      | One-time (or rare re-auth) seed of the sidecar: pulls cookies from operator's real browser via`browser_cookie3`, converts to Playwright `storage_state`, POSTs to `/admin/refresher-bootstrap`                                                                                         | none directly (uploads to own app, which proxies to sidecar)                                                                                                                                                                                                                                                      | Reads local browser cookie store only; writes nothing locally — result lands in sidecar's`state.json`                                                                                                                   | `WEB_BASE_URL=... REFRESHER_API_KEY=... python scripts/bootstrap_refresher_session.py --browser chrome`                                                                                                                           |
| Android bookmarklet (`javascript:` URI, phone Chrome bookmark)                                                | Reads`SAPISID` from `document.cookie` on a signed-in google.com tab, builds a hidden form, POSTs it (no `fetch`, no CORS) to `/admin/sapisid-relay` in a new tab                                                                                                                     | none (reads the phone's already-authenticated Chrome session, no navigation of its own)                                                                                                                                                                                                                           | Reads the phone's live browser cookie store only; writes nothing — result lands in the running server process via the relay endpoint below                                                                                | Tapped bookmark only — see "Refreshing cookies from the parent's Android phone" above; no CLI equivalent                                                                                                                           |
| `POST /admin/sapisid-relay` ([admin.py](src/familylink_server/routers/admin.py))                               | Android bookmarklet target: reads`sapisid` + `token` form fields, verifies `token` against `SAPISID_RELAY_TOKEN` (`secrets.compare_digest`), hot-swaps the in-process client via `reinit_with_sapisid()`, verifies with `get_members()` before reporting success — no restart | none directly; the SAPISID itself came from the phone's browser reading`document.cookie` on a signed-in Google tab                                                                                                                                                                                              | Sets`FAMILYLINK_SAPISID` env var in the running process only (not persisted to `.env` or Coolify)                                                                                                                      | Called by the bookmarklet above; no CLI equivalent                                                                                                                                                                                  |
