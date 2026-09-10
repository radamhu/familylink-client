# Family Link

A non-official Python package to interact with Google Family Link and linux machines, to manage your kids' screen time.

<p align="center">
  <img src="logo.jpeg" alt="Family Link logo" width="200" height="200">
</p>

## What it does for you as a parent

- Set per-app daily time limits, block apps, or always-allow them
- Lock/unlock a kid's device, or power off a Linux PC once its quota runs out
- See usage history and today's top apps on a dashboard
- Manage everything from Discord: `/apps`, `/devices`, `/usage`, plus a nightly summary
- Get push notifications for low time remaining and new homework (eKRÉTA, optional)

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

## Documentation

- [Development setup](docs/development.md) — local install, Makefile, Docker dev workflow
- [Server deployment](docs/deployment.md) — OAuth credentials, env vars, migrations, Coolify + cookie-refresh sidecar
- [Linux machine management](docs/linux-machines.md) — SSH-based lock/power-off enforcement
- [eKRÉTA homework scraping](docs/ekreta.md) — optional
- [ntfy notification setup](docs/ntfy.md) — optional
