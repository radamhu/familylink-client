# Family Link

A non-official Python package to interact with Google Family Link, to manage your kids' screen time.

<p align="center">
  <img src="logo.svg" alt="Family Link logo" width="200" height="200">
</p>

## Features

* 📊 Daily screen time tracking per child
* 📱 Top 10 most-used apps with detailed statistics
* 🔒 Remote lock/unlock devices (bi-directional sync with Family Link app)
* 📲 Installed app counts and blocked app lists
* 👤 Child profile information (name, email, birthday, age band)
* 📅 Per-application usage breakdown
* 🔄 Multi-device support

## Two modes of operation

This project ships two independent ways to manage Family Link:

|                               | CLI                                           | Web server                                      |
| ----------------------------- | --------------------------------------------- | ----------------------------------------------- |
| **Config storage**      | `config.csv` (declarative, file-based)      | PostgreSQL (`app_configs` table)              |
| **Workflow**            | Run as a cron job; pushes diffs to the API    | Interactive web UI; changes applied immediately |
| **Auth**                | Browser cookies or `FAMILYLINK_COOKIES_B64` | Same cookie auth + Google OAuth login           |
| **History / audit log** | None                                          | `usage_snapshots`, `audit_log` tables       |
| **When to use**         | Scripted or headless enforcement              | Always-on dashboard with persistent history     |

If you run the server, you do not need `config.csv`. Limit rules are managed through the web UI and stored in the database. The only CLI commands that remain useful in a server deployment are `export-cookies` (to refresh the Google session) and `fetch-config` (to export current API state as a CSV snapshot).

## Prerequisites

1. Have a Google Family Link family set up (parent + child)
2. Be signed into Chrome or Firefox as the **parent** account
3. Visit **[https://familylink.google.com](https://familylink.google.com)** at least once in that browser (this establishes the necessary session)

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
familylink --dry-run config.csv              # Preview changes without applying
familylink config.csv                         # Apply changes
familylink --browser chrome config.csv        # Use Chrome instead of Firefox
familylink export-cookies --base64            # Export cookies for cloud deployment
familylink export-cookies --browser chrome    # Export from Chrome, write cookies.txt
```

### Options

| Flag                   | Description                                     |
| ---------------------- | ----------------------------------------------- |
| `--dry-run`          | Print what would be done without making changes |
| `--browser`          | `firefox` (default) or `chrome`             |
| `--cookie-file`      | Path to a Netscape-format cookies file          |
| `-v` / `--verbose` | Enable debug logging                            |

### export-cookies options

| Flag                  | Description                                                |
| --------------------- | ---------------------------------------------------------- |
| `--browser`         | `firefox` (default) or `chrome`                        |
| `--output` / `-o` | Output file path (default:`cookies.txt`)                 |
| `--base64`          | Also print the base64 value for `FAMILYLINK_COOKIES_B64` |

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
| `make install`     | First-time setup — creates `.venv`, installs all deps and pre-commit hooks      |
| `make dev`         | Start the uvicorn dev server locally with hot reload (`http://localhost:8000`)   |
| `make migrate`     | After pulling changes that add Alembic migrations — applies them to your local DB |
| `make test`        | Run the full test suite before committing                                          |
| `make test-unit`   | Fast feedback loop — unit tests only, no DB required                              |
| `make test-server` | Server/integration tests (requires DB env vars from `.env`)                      |
| `make lint`        | Check code style without changing files                                            |
| `make lint-fix`    | Auto-fix lint issues in place                                                      |
| `make format`      | Format all source files with ruff                                                  |
| `make typecheck`   | Run mypy static type checking                                                      |
| `make clean`       | Wipe `.venv`, caches, and build artifacts for a clean slate                      |

**Docker (local stack)**

| Command                  | When to use                                                                                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make docker-up`       | Start the stack (db + web) using the**current image** — use when the image is already up to date and you just need the containers running     |
| `make docker-deploy`   | **Standard deploy** — refreshes cookies in `.env`, rebuilds the `web` image, and restarts the container; run this after every code change |
| `make docker-restart`  | Same as `docker-deploy`; prefer `docker-deploy` for clarity                                                                                      |
| `make docker-build`    | Refresh cookies and rebuild the `web` image without restarting (pre-warm before `docker-up`)                                                     |
| `make refresh-cookies` | Manually refresh `FAMILYLINK_COOKIES_B64` in `.env` from Chrome without rebuilding — useful when only the session has expired                   |
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

| Variable                    | Description                                                                                             |
| --------------------------- | ------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`            | PostgreSQL connection string:`postgresql+asyncpg://user:password@host/dbname`                         |
| `SECRET_KEY`              | Random 32-byte hex (generate:`python -c "import secrets; print(secrets.token_hex(32))"`)              |
| `GOOGLE_CLIENT_ID`        | From Google OAuth credentials                                                                           |
| `GOOGLE_CLIENT_SECRET`    | From Google OAuth credentials                                                                           |
| `FAMILYLINK_GOOGLE_EMAIL` | Parent's Gmail address                                                                                  |
| `FAMILYLINK_COOKIES_B64`  | Base64 output from `familylink export-cookies --base64`                                               |
| `CACHE_TTL_SECONDS`       | Cache duration in seconds (default:`900`)                                                             |
| `DEBUG`                   | Set to `true` to disable `Secure` flag on the session cookie — required for local HTTP (see below) |

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

### Local Docker development

Running the server locally via `docker compose up` requires two extra steps because Google OAuth sets a `Secure` session cookie that browsers silently drop over plain HTTP.

**1. Add `DEBUG=true` to your `.env`**

```env
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

### Troubleshooting

- **Database connection fails**: Verify `DATABASE_URL` format and that your database is reachable from the deployment platform
- **"Could not find SAPISID"**: The cookies have expired — re-run `familylink export-cookies --base64` and update `FAMILYLINK_COOKIES_B64`
- **OAuth redirect fails**: Check that the redirect URI in Google Cloud Console exactly matches your deployed URL
- **Login succeeds but every page redirects back to `/auth/login`**: The session cookie is being dropped. If running locally over HTTP, set `DEBUG=true` in `.env` (see above)
