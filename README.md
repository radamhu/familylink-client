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

## Prerequisites

1. Have a Google Family Link family set up (parent + child)
2. Be signed into Chrome or Firefox as the **parent** account
3. Visit **[https://familylink.google.com](https://familylink.google.com)** at least once in that browser (this establishes the necessary session)

### First-time setup

```bash
# Default: reads cookies from Firefox
familylink --dry-run config.csv

# If you use Chrome:
familylink --browser chrome --dry-run config.csv
```

If you see `Could not find SAPISID`, the tool couldn't find the cookie in your browser. Try:

- **Specify your browser:** `familylink --browser chrome config.csv`
- **Export cookies to a file** (e.g. with the "Get cookies.txt" Chrome extension), then: `familylink --cookie-file /path/to/cookies.txt config.csv`
- **Set the SAPISID value directly** (find it in DevTools > Application > Cookies > `.google.com` > `SAPISID`):
  ```
  export FAMILYLINK_SAPISID=your_sapisid_value_here
  familylink config.csv
  ```

### Environment variables

| Variable                    | Purpose                                                                                     |
| --------------------------- | ------------------------------------------------------------------------------------------- |
| `FAMILYLINK_COOKIES_B64`  | Base64-encoded `cookies.txt` content — preferred for cloud/Docker (no filesystem needed) |
| `FAMILYLINK_COOKIE_FILE`  | Path to a Netscape-format cookies file                                                      |
| `FAMILYLINK_SAPISID`      | Raw SAPISID cookie value only (not recommended — session cookies also required)            |
| `FAMILYLINK_BROWSER`      | `firefox`, `chrome`, or `txt` (cookie file only)                                      |
| `FAMILYLINK_PROFILES_DIR` | When cwd is under this directory, per-profile auth is used                                  |
| `FAMILYLINK_AUTHUSER`     | Google account index (`0`, `1`, `2`...) for multi-account setups                      |

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

| Variable | Description |
| -------- | ----------- |
| `DATABASE_URL` | PostgreSQL connection string: `postgresql+asyncpg://user:password@host/dbname` |
| `SECRET_KEY` | Random 32-byte hex (generate: `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `GOOGLE_CLIENT_ID` | From Google OAuth credentials |
| `GOOGLE_CLIENT_SECRET` | From Google OAuth credentials |
| `FAMILYLINK_GOOGLE_EMAIL` | Parent's Gmail address |
| `FAMILYLINK_COOKIES_B64` | Base64 output from `familylink export-cookies --base64` |
| `CACHE_TTL_SECONDS` | Cache duration in seconds (default: `900`) |

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

### Troubleshooting

- **Database connection fails**: Verify `DATABASE_URL` format and that your database is reachable from the deployment platform
- **"Could not find SAPISID"**: The cookies have expired — re-run `familylink export-cookies --base64` and update `FAMILYLINK_COOKIES_B64`
- **OAuth redirect fails**: Check that the redirect URI in Google Cloud Console exactly matches your deployed URL
