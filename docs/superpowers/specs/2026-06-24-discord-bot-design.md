# Discord Bot Integration — Design Spec

**Date:** 2026-06-24
**Status:** Approved

## Goal

Add a Discord bot to the existing FamilyLink FastAPI server. The bot runs in the same container as the web server, shares the `FamilyLinkService` singleton, and provides:

1. Full slash-command parity with the web UI (read + write operations)
2. Role-based authorization (Discord role name, configurable)
3. Real-time change notifications to a Discord channel whenever the web UI or bot makes a write
4. Scheduled daily usage summary per child with action buttons

---

## 1. Architecture

The bot starts as an `asyncio.create_task()` inside the existing FastAPI `lifespan` context manager, sharing the same event loop as uvicorn. It holds references to the existing `FamilyLinkService` singleton and a new `DiscordNotifier` service.

```
FastAPI lifespan
  ├── init FamilyLinkService (existing)
  ├── init DiscordNotifier   (new — holds bot reference + channel ID)
  ├── asyncio.create_task(bot_task_with_restart(bot, token))
  └── yields (server is up)
        ├── existing routers  ──► DiscordNotifier.notify_change()  on every write
        └── bot commands      ──► FamilyLinkService  for all read/write actions
```

If any of `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, or `DISCORD_CHANNEL_ID` is absent, the bot task is skipped entirely with a warning log; the web server starts normally.

### New files

```
src/familylink_server/
  ├── bot/
  │   ├── __init__.py
  │   ├── client.py          # FamilyLinkBot subclass: on_ready, command tree sync, restart wrapper
  │   ├── commands/
  │   │   ├── __init__.py
  │   │   ├── apps.py        # /apps command group
  │   │   ├── devices.py     # /devices command group
  │   │   └── usage.py       # /usage, /status, /refresh commands
  │   ├── views.py           # discord.ui.View subclasses (action button rows)
  │   └── embeds.py          # Embed builder helpers
  └── services/
      └── discord_notifier.py   # Outbound notification interface
```

### Restart wrapper

`bot.start()` runs inside a `while True` loop in `client.py`. On unhandled exception it logs the error, waits 30 s, then reconnects. A `asyncio.CancelledError` (from lifespan shutdown) breaks the loop cleanly.

---

## 2. Slash Commands & Authorization

### Authorization

A single `app_commands.check()` decorator (`require_discord_role`) is applied to every command and button interaction. It verifies the invoking user has a role whose name matches `DISCORD_ALLOWED_ROLE`. Unauthorized users receive an ephemeral error message; no action is taken.

### Command groups (guild-scoped to `DISCORD_GUILD_ID`)

Guild-scoped commands sync instantly on bot startup via `bot.tree.sync(guild=...)`.

#### `/apps`

| Subcommand | Parameters | Action |
|---|---|---|
| `list` | `[child]` | Paginated embed: app name · state pill · today's usage |
| `limit` | `<package> <minutes> [child]` | Set time limit → confirmation embed + Undo button |
| `block` | `<package> [child]` | Block app → confirmation embed + Unblock / Always Allow buttons |
| `allow` | `<package> [child]` | Always-allow app → confirmation embed + Remove button |

#### `/devices`

| Subcommand | Parameters | Action |
|---|---|---|
| `list` | `[child]` | Embed cards: device name · lock state · last seen |
| `lock` | `<device> [child]` | Lock device → confirmation embed + Unlock button |
| `unlock` | `<device> [child]` | Unlock device → confirmation embed + Lock button |

#### `/usage`

| Subcommand | Parameters | Action |
|---|---|---|
| `today` | `[child]` | Screen time by app today, bar-style embed |
| `history` | `[child] [days=7]` | Daily totals over N days |

#### Top-level

| Command | Action |
|---|---|
| `/status` | Dashboard overview — all children, all devices, top 5 apps |
| `/refresh` | Invalidate cache for all children |

### Autocomplete

All `child` parameters use `app_commands.autocomplete` populated from `FamilyLinkService.get_members()`, returning real child display names. When `child` is omitted: if there is exactly one supervised child, that child is used automatically; if there are multiple children, the command replies with an ephemeral error asking the user to specify.

### Action buttons

Confirmation embeds include a `discord.ui.View` with a contextual button (e.g. "Unblock" after a block action). Views have `timeout=300` (5 minutes). Button interactions go through the same `require_discord_role` check. Clicking a button calls the same `FamilyLinkService` method as the slash command it mirrors.

---

## 3. Notification System

### Real-time change alerts

Every write operation in the existing routers calls `DiscordNotifier.notify_change()` after the Google API call succeeds. The notifier posts an embed to `DISCORD_CHANNEL_ID`:

```
🔒 App Blocked
Child: Emma  ·  App: TikTok (com.zhiliaoapp.musically)
By: web UI  ·  12:34 UTC

[ Unblock ]  [ Always Allow ]
```

The `by` field is `"web UI"` for router-originated actions and the Discord username for bot-originated actions. Buttons on notification embeds are role-gated and expire after 5 minutes.

### Scheduled daily summary

A `@discord.ext.tasks.loop` task fires once daily at `DISCORD_SUMMARY_TIME` (HH:MM UTC, default `20:00`). It posts one embed per child:

```
📊 Daily Summary — Emma  ·  Tuesday 24 Jun
Total screen time: 3h 12m

YouTube          ████████░░  1h 45m
Minecraft        ████░░░░░░    58m
WhatsApp         ██░░░░░░░░    29m

[ Lock Device ]  [ View History ]
```

Bar widths are proportional to the longest session, rendered with Unicode block characters (`█` / `░`). Buttons trigger the same internal logic as the corresponding slash commands. If the bot starts after the scheduled time has already passed for the current day, it waits until the next window without posting retroactively.

---

## 4. Configuration

### New environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DISCORD_BOT_TOKEN` | yes* | — | Bot token from Discord Developer Portal |
| `DISCORD_GUILD_ID` | yes* | — | Server ID for guild-scoped command sync |
| `DISCORD_CHANNEL_ID` | yes* | — | Channel ID for outbound notifications |
| `DISCORD_ALLOWED_ROLE` | no | `Parent` | Role name required to run commands |
| `DISCORD_SUMMARY_TIME` | no | `20:00` | Daily summary time (HH:MM UTC) |

*Required only when bot is enabled. All three must be set together; if any is missing, the bot task is skipped with a warning log.

These are added to `config.py` as `Optional` fields on the existing `Settings` class and documented in `.env.example`.

### New dependency

```
discord.py>=2.4
```

Added to `pyproject.toml` under `[project.optional-dependencies]` in the `server` extras group. No separate extra needed — the bot is same-process.

### Docker & deployment

No changes to `Dockerfile` or `docker-compose.yml`. The new env vars flow through the existing `env_file: .env` mechanism.

---

## 5. What Is Not Changing

- Existing web UI routes, templates, and HTMX behavior are unchanged
- `FamilyLinkService` API is unchanged; the bot is a new consumer of it
- Database schema is unchanged; `audit_log` already captures all write actions
- Docker build and compose topology are unchanged (still one `web` + one `db` service)
- CLI (`familylink` package) is unchanged
