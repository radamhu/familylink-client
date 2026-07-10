# Graph Report - .  (2026-07-03)

## Corpus Check
- 120 files · ~82,147 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1072 nodes · 1865 edges · 62 communities (49 shown, 13 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 345 edges (avg confidence: 0.77)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Server Config + DB Session|Server Config + DB Session]]
- [[_COMMUNITY_Async Services + Linux Poller|Async Services + Linux Poller]]
- [[_COMMUNITY_Pydantic Data Models|Pydantic Data Models]]
- [[_COMMUNITY_CLI Commands|CLI Commands]]
- [[_COMMUNITY_Discord Bot Embeds|Discord Bot Embeds]]
- [[_COMMUNITY_Server Lifecycle + Bot Client|Server Lifecycle + Bot Client]]
- [[_COMMUNITY_FastAPI Admin Routes|FastAPI Admin Routes]]
- [[_COMMUNITY_App Management Routes|App Management Routes]]
- [[_COMMUNITY_Discord Slash Commands|Discord Slash Commands]]
- [[_COMMUNITY_Bot Command Tests|Bot Command Tests]]
- [[_COMMUNITY_Discord UI Views|Discord UI Views]]
- [[_COMMUNITY_App Usage Models|App Usage Models]]
- [[_COMMUNITY_DevOps + Project Docs|DevOps + Project Docs]]
- [[_COMMUNITY_Design Concepts + Plans|Design Concepts + Plans]]
- [[_COMMUNITY_Discord Apps Command Group|Discord Apps Command Group]]
- [[_COMMUNITY_API Client Methods|API Client Methods]]
- [[_COMMUNITY_Linux Machine Routes|Linux Machine Routes]]
- [[_COMMUNITY_Cookie Hot-Reload Tests|Cookie Hot-Reload Tests]]
- [[_COMMUNITY_Server Settings|Server Settings]]
- [[_COMMUNITY_Cookie Auth Resolution|Cookie Auth Resolution]]
- [[_COMMUNITY_Discord Linux Commands|Discord Linux Commands]]
- [[_COMMUNITY_Discord Notification Service|Discord Notification Service]]
- [[_COMMUNITY_DB Model Tests|DB Model Tests]]
- [[_COMMUNITY_Dashboard + Constants|Dashboard + Constants]]
- [[_COMMUNITY_Discord Notifier Tests|Discord Notifier Tests]]
- [[_COMMUNITY_API Response Parsers|API Response Parsers]]
- [[_COMMUNITY_Google OAuth Flow|Google OAuth Flow]]
- [[_COMMUNITY_FamilyLink Service Tests|FamilyLink Service Tests]]
- [[_COMMUNITY_Unit Client Tests|Unit Client Tests]]
- [[_COMMUNITY_Bot Usage Commands|Bot Usage Commands]]
- [[_COMMUNITY_ORM Models|ORM Models]]
- [[_COMMUNITY_Bot UI View Tests|Bot UI View Tests]]
- [[_COMMUNITY_Discord Session Alert Tests|Discord Session Alert Tests]]
- [[_COMMUNITY_Linux Machine ORM Model|Linux Machine ORM Model]]
- [[_COMMUNITY_Linux Usage Snapshot Model|Linux Usage Snapshot Model]]
- [[_COMMUNITY_API GET Methods|API GET Methods]]
- [[_COMMUNITY_Time Limits + Session Errors|Time Limits + Session Errors]]
- [[_COMMUNITY_Linux Bonus Time Bot Commands|Linux Bonus Time Bot Commands]]
- [[_COMMUNITY_Members Route Tests|Members Route Tests]]
- [[_COMMUNITY_Alembic Migration Env|Alembic Migration Env]]
- [[_COMMUNITY_Cookie Jar Resolution|Cookie Jar Resolution]]
- [[_COMMUNITY_Auth + SAPISIDHASH Generation|Auth + SAPISIDHASH Generation]]
- [[_COMMUNITY_Member + Usage Queries|Member + Usage Queries]]
- [[_COMMUNITY_Linux Machines DB Migration|Linux Machines DB Migration]]
- [[_COMMUNITY_Bonus Minutes DB Migration|Bonus Minutes DB Migration]]
- [[_COMMUNITY_GitHub Release Automation|GitHub Release Automation]]
- [[_COMMUNITY_Lint + Pre-Commit Pipeline|Lint + Pre-Commit Pipeline]]
- [[_COMMUNITY_Brand Identity|Brand Identity]]
- [[_COMMUNITY_Python Dependencies|Python Dependencies]]
- [[_COMMUNITY_Auth Package Init|Auth Package Init]]
- [[_COMMUNITY_DB Package Init|DB Package Init]]
- [[_COMMUNITY_Server Package Init|Server Package Init]]
- [[_COMMUNITY_Router Package Init|Router Package Init]]
- [[_COMMUNITY_Cookie Reinit Method|Cookie Reinit Method]]
- [[_COMMUNITY_Services Package Init|Services Package Init]]
- [[_COMMUNITY_Test Configuration|Test Configuration]]
- [[_COMMUNITY_API Output|API Output]]
- [[_COMMUNITY_Package Root|Package Root]]

## God Nodes (most connected - your core abstractions)
1. `FamilyLinkService` - 67 edges
2. `app()` - 40 edges
3. `FamilyLink` - 39 edges
4. `DiscordNotifier` - 35 edges
5. `get_service()` - 35 edges
6. `require_discord_role()` - 23 edges
7. `get_session()` - 23 edges
8. `poll_machine()` - 23 edges
9. `AppsGroup` - 18 edges
10. `FamilyLinkBot` - 16 edges

## Surprising Connections (you probably didn't know these)
- `GitHub Copilot Instructions` --semantically_similar_to--> `CLAUDE.md Project Instructions`  [INFERRED] [semantically similar]
  .github/copilot-instructions.md → CLAUDE.md
- `Pre-Commit Config` --semantically_similar_to--> `Ruff Lint Workflow`  [INFERRED] [semantically similar]
  .pre-commit-config.yaml → .github/workflows/lint.yml
- `_make_service()` --calls--> `SessionExpiredError`  [INFERRED]
  tests/server/test_health_check.py → src/familylink/client.py
- `client()` --calls--> `FamilyLink`  [INFERRED]
  tests/unit/test_client.py → src/familylink/client.py
- `test_require_discord_role_fails_no_guild()` --calls--> `require_discord_role()`  [INFERRED]
  tests/server/test_bot_commands.py → src/familylink_server/bot/commands/__init__.py

## Import Cycles
- 1-file cycle: `src/familylink/client.py -> src/familylink/client.py`

## Hyperedges (group relationships)
- **Linux Machine Management Feature Set** — docs_superpowers_plans_2026_06_25_linux_machine_control, docs_superpowers_plans_2026_06_25_linux_bonus_time, docs_superpowers_plans_2026_06_25_linux_machines_key_gen, concept_linux_ssh_enforcement [INFERRED 0.95]
- **CI/CD Pipeline** — _github_workflows_ci_yml, _github_workflows_lint_yml, _github_workflows_publish_yml, _github_workflows_release_drafter_yml, _pre_commit_config_yaml [INFERRED 0.95]
- **Server Web Service Feature Plans** — docs_superpowers_plans_2026_06_19_server_web_service, docs_superpowers_plans_2026_06_22_apps_per_child, docs_superpowers_plans_2026_06_24_discord_bot, docs_superpowers_plans_2026_06_30_dashboard_redesign, concept_familylink_server_package [INFERRED 0.90]
- **HTMX Single-Expand Child Detail Pattern** — src_familylink_server_templates_partials_child_strip, src_familylink_server_templates_partials_child_expanded, src_familylink_server_templates_dashboard [EXTRACTED 1.00]
- **Linux Machine Control Subsystem** — docs_superpowers_specs_2026_06_25_linux_machine_control_design, concept_linux_poller, src_familylink_server_templates_partials_linux_machine_card [INFERRED 0.95]
- **Google Auth Resilience + Discord Alerting System** — docs_superpowers_specs_2026_06_30_oauth_bearer_auth_resilience_design, concept_health_check_loop, concept_discord_notifier [EXTRACTED 1.00]

## Communities (62 total, 13 thin omitted)

### Community 0 - "Server Config + DB Session"
Cohesion: 0.05
Nodes (88): Application settings loaded from environment variables., get_session(), Async SQLAlchemy session factory., Get an async database session.      Yields an AsyncSession from the configured e, get_service(), Singleton service wrapping the FamilyLink client with async + cache-aside., FastAPI dependency — returns the singleton., app() (+80 more)

### Community 1 - "Async Services + Linux Poller"
Cohesion: 0.06
Nodes (58): make_session(), AsyncSession, Async context manager for use outside FastAPI dependency injection.      Use in, poll_machine(), poller_loop(), Background asyncio task that polls Linux machines and enforces screen-time limit, Main poll loop — iterates all enabled machines every POLL_INTERVAL seconds., Poll one machine: skip if powered off, accumulate active seconds, enforce limits (+50 more)

### Community 2 - "Pydantic Data Models"
Cohesion: 0.05
Nodes (53): BaseModel, Enum, AdSupportStatus, AlwaysAllowedAppInfo, AlwaysAllowedState, ApiHeader, App, AppId (+45 more)

### Community 3 - "CLI Commands"
Cohesion: 0.07
Nodes (44): _apply_config(), _cmd_export_cookies(), _cmd_fetch_config(), _create_default_config(), _get_expected_limits(), _load_config(), main(), _mins_to_hhmm() (+36 more)

### Community 4 - "Discord Bot Embeds"
Cohesion: 0.07
Nodes (44): apps_list_embed(), _bar(), change_embed(), daily_summary_embed(), devices_list_embed(), _fmt(), Embed, Discord embed builder functions. (+36 more)

### Community 5 - "Server Lifecycle + Bot Client"
Cohesion: 0.05
Nodes (41): _bot_task_with_restart(), Run bot.start() in a restart loop; exits cleanly on CancelledError., health_check_loop(), lifespan(), HTMLResponse, Request, FastAPI application factory., Return a 503 page with re-export instructions when Google cookies expire. (+33 more)

### Community 6 - "FastAPI Admin Routes"
Cohesion: 0.05
Nodes (36): FastAPI, HTMLResponse, Admin endpoints — protected, for operational management., Request body for the refresh-cookies endpoint., Reconnect page — shows the SAPISID paste form., Hot-swap the FamilyLink client with fresh cookies. No server restart needed., reconnect_page(), refresh_cookies() (+28 more)

### Community 7 - "App Management Routes"
Cohesion: 0.08
Nodes (38): allow_app(), _app_state(), apps_page(), block_app(), _child_name(), AsyncSession, HTMLResponse, Request (+30 more)

### Community 8 - "Discord Slash Commands"
Cohesion: 0.08
Nodes (16): DiscordNotifier, Sends embeds to a configured Discord channel., Called by the bot's on_ready once the channel is resolved., FamilyLinkService, datetime, Always-allow an app and invalidate the usage cache., Wraps the synchronous FamilyLink client for async FastAPI use., Return True if the last Google API call failed due to auth. (+8 more)

### Community 9 - "Bot Command Tests"
Cohesion: 0.08
Nodes (34): _make_interaction(), Interaction, Tests for bot authorization and child resolution helpers., Test that /apps block calls block_app on the service., Test that /apps limit calls set_app_limit on the service., Test that /apps allow calls always_allow_app on the service., Test that /apps block is rejected when the caller lacks the required role., Test that /devices lock calls lock_device on the service. (+26 more)

### Community 10 - "Discord UI Views"
Cohesion: 0.12
Nodes (19): Button, AppAllowView, AppBlockView, AppLimitView, DeviceLockView, DeviceUnlockView, Interaction, Discord UI views (action button rows for embeds). (+11 more)

### Community 11 - "App Usage Models"
Cohesion: 0.09
Nodes (23): AppUsage, App usage response model., Get the title of an app., _apps_today(), FamilyLinkBot, _fetch_linux_rows(), _linux_rows_for_child(), AbstractAsyncContextManager (+15 more)

### Community 12 - "DevOps + Project Docs"
Cohesion: 0.12
Nodes (30): GitHub Copilot Instructions, CI Workflow, Publish to PyPI Workflow, CLAUDE.md Project Instructions, CHILD_COLORS Dashboard Strip Layout, Cookie Hot-Reload Without Container Restart, CookieResolver — Multi-Source Auth Resolution, Coolify Deployment with Cookie Sync (+22 more)

### Community 13 - "Design Concepts + Plans"
Cohesion: 0.09
Nodes (30): Color-by-index assignment: purple/blue/green/orange/red, Coolify cookie push: --coolify flag patches env var via REST, Dashboard status strips: stacked child rows, single-expand, DiscordNotifier: outbound change/alert notification service, Discord slash command groups: /apps /devices /usage /linux, FamilyLinkBot: discord.py bot with restart wrapper, health_check_loop: 30-min probe with Discord alerting, Bonus time: bonus_mins column extends daily_limit_mins (+22 more)

### Community 14 - "Discord Apps Command Group"
Cohesion: 0.12
Nodes (18): AppsGroup, Interaction, Discord /apps command group., Set a daily usage limit., Slash command group: /apps list | limit | block | allow., DevicesGroup, Interaction, Discord /devices command group. (+10 more)

### Community 15 - "API Client Methods"
Cohesion: 0.15
Nodes (11): FamilyLink, Set daily time limit (minutes) for a device., Disable all time limits for a device (today)., Re-enable previous time limits for a device., Enable downtime for a device (today)., Disable downtime for a device (today)., Client to interact with Google Family Link., Set a daily time limit (minutes) on an app. (+3 more)

### Community 16 - "Linux Machine Routes"
Cohesion: 0.18
Nodes (23): JSONResponse, bonus_machine(), _child_names(), delete_machine(), edit_machine_form(), generate_key_pair(), _get_machine_or_404(), new_machine_form() (+15 more)

### Community 17 - "Cookie Hot-Reload Tests"
Cohesion: 0.12
Nodes (21): _make_service(), Tests for cookie hot-reload endpoint and FamilyLinkService methods., POST /admin/refresh-cookies with valid session and SAPISID should return 204., Create a service instance bypassing __init__ (avoids FamilyLink() cookie lookup), auth_failed property should return False on a fresh instance., set_auth_failed(True) should make auth_failed return True., set_auth_failed(False) after True should make auth_failed return False., reinit_with_cookies should replace _client with a new FamilyLink instance. (+13 more)

### Community 18 - "Server Settings"
Cohesion: 0.12
Nodes (17): BaseSettings, time, Application settings loaded from environment variables., True when all three required Discord vars are set., Parse HH:MM string into a UTC datetime.time., Settings, Tests for server configuration., Test that Discord is disabled when no tokens are set. (+9 more)

### Community 19 - "Cookie Auth Resolution"
Cohesion: 0.14
Nodes (15): CookieResolver, Cookie and SAPISID resolution for the Family Link API.  Auth priority (first mat, Resolves a SAPISID string and optional CookieJar from configured sources., Path, Tests for familylink.auth.CookieResolver., CookieResolver resolves SAPISID from FAMILYLINK_COOKIES_B64 env var., CookieResolver resolves SAPISID from FAMILYLINK_SAPISID env var (no jar)., CookieResolver resolves SAPISID from a cookie file when browser='txt'. (+7 more)

### Community 20 - "Discord Linux Commands"
Cohesion: 0.17
Nodes (15): LinuxGroup, AbstractAsyncContextManager, AsyncSession, Discord /linux command group., Slash command group: /linux bonus., _make_interaction(), _make_machine(), _make_session_ctx() (+7 more)

### Community 21 - "Discord Notification Service"
Cohesion: 0.12
Nodes (13): _change_embed(), init_notifier(), Embed, Outbound Discord notification service., Post a daily usage summary embed. No-op if channel not yet ready., Post a session-expired alert. No-op if channel not ready., Post a session-restored confirmation. No-op if channel not ready., Create and store the singleton. Called once in lifespan. (+5 more)

### Community 22 - "DB Model Tests"
Cohesion: 0.11
Nodes (17): db_session(), Tests for database models., LinuxUsageSnapshot.bonus_mins defaults to 0., LinuxUsageSnapshot.bonus_mins stores an explicit value., Provide an in-memory SQLite session for testing., Test AppConfig model insert and read operations., Test UsageSnapshot model insert., Test DeviceSnapshot model with unique constraint on device_id. (+9 more)

### Community 23 - "Dashboard + Constants"
Cohesion: 0.21
Nodes (14): Any, Shared constants for the familylink server., child_collapse(), child_detail(), dashboard(), _get_child_data(), AsyncSession, HTMLResponse (+6 more)

### Community 24 - "Discord Notifier Tests"
Cohesion: 0.12
Nodes (15): channel(), notifier(), Tests for DiscordNotifier service., Create a test notifier instance., Create a mock Discord TextChannel., Notifier should silently skip if channel not set., Notifier should send embed when channel is set., Notifier should pass view parameter to channel.send. (+7 more)

### Community 25 - "API Response Parsers"
Cohesion: 0.20
Nodes (12): parse_apps_and_usage(), parse_members_response(), parse_time_limit(), Protobuf-JSON response parsers for the Family Link API., Parse /timeLimit positional list response.      Returns {day_int: {"avail_start", Convert /appsandusage positional list to an AppUsage-compatible dict., Convert /families/mine/members positional list to a MembersResponse-compatible d, test_parse_apps_and_usage_empty_lists() (+4 more)

### Community 26 - "Google OAuth Flow"
Cohesion: 0.20
Nodes (13): callback(), login(), logout(), _make_session(), RedirectResponse, Request, Google OAuth 2.0 login flow and session cookie dependency., FastAPI dependency — returns authenticated user email or raises HTTP 401/403. (+5 more)

### Community 27 - "FamilyLink Service Tests"
Cohesion: 0.14
Nodes (13): mock_client(), Tests for FamilyLinkService singleton with async wrapper and cache-aside., Return a MagicMock that mimics the FamilyLink client., Return a FamilyLinkService bypassing __init__, with TTL=0 (no caching)., get_members should call the client and return its result., get_apps_and_usage should forward child_id to the client., lock_device should call the client with the correct keyword arguments., unlock_device should call the client with the correct keyword arguments. (+5 more)

### Community 28 - "Unit Client Tests"
Cohesion: 0.14
Nodes (13): client(), Unit tests for FamilyLink client public API., block_app() POSTs to the apps:updateRestrictions endpoint., always_allow_app() POSTs to the apps:updateRestrictions endpoint., remove_app_limit() POSTs to the apps:updateRestrictions endpoint., FamilyLink client wired to a temp cookie file with no browser/env auth., get_members() parses the raw list response into a MembersResponse., set_app_limit() POSTs to the apps:updateRestrictions endpoint with the right bod (+5 more)

### Community 29 - "Bot Usage Commands"
Cohesion: 0.23
Nodes (11): Command, Register command groups and create the scheduled task., make_refresh_command(), make_status_command(), make_summary_command(), AbstractAsyncContextManager, AsyncSession, Discord /usage, /status, and /refresh commands. (+3 more)

### Community 30 - "ORM Models"
Cohesion: 0.21
Nodes (12): DeclarativeBase, AppConfig, AuditLog, Base, DeviceSnapshot, SQLAlchemy ORM models., SQLAlchemy declarative base for all ORM models., App configuration settings for a child's device usage. (+4 more)

### Community 31 - "Bot UI View Tests"
Cohesion: 0.22
Nodes (12): _make_interaction(), Tests for Discord UI action views., Unblock button calls always_allow_app and sends a response., Always Allow button calls always_allow_app., Unlock button calls unlock_device., Lock Device button calls lock_device., Unauthorized user gets ephemeral error and service is not called., test_app_block_view_always_allow_calls_service() (+4 more)

### Community 32 - "Discord Session Alert Tests"
Cohesion: 0.17
Nodes (11): channel(), notifier(), Tests for Discord session expired/restored alert methods., Create a DiscordNotifier instance for testing., Create a mock Discord TextChannel., notify_session_expired sends an embed with 'expired' in the title., notify_session_restored sends an embed with 'restored' in the title., Both methods are silent no-ops when the Discord channel is not yet set. (+3 more)

### Community 33 - "Linux Machine ORM Model"
Cohesion: 0.22
Nodes (9): LinuxMachine, Initialise with Python-level defaults for optional columns., Registered Linux machine managed via SSH., create_machine(), linux_machines_page(), _machine_context(), RedirectResponse, Create a new Linux machine record. (+1 more)

### Community 34 - "Linux Usage Snapshot Model"
Cohesion: 0.25
Nodes (8): LinuxUsageSnapshot, Daily active-session accumulator for a Linux machine., Initialise with Python-level defaults for optional columns., lock_machine(), Lock the machine immediately and return the updated card partial., _today_snapshot(), LinuxUsageSnapshot has expected columns., test_linux_usage_snapshot_model_attributes()

### Community 35 - "API GET Methods"
Cohesion: 0.25
Nodes (4): Response, Get apps and usage information for a child., Get time limit for a child., Get applied time limits for a child.

### Community 36 - "Time Limits + Session Errors"
Cohesion: 0.25
Nodes (7): Get applied time limits for a child (today)., Google session has expired or been invalidated.      Re-export cookies and updat, SessionExpiredError, get_members() raises SessionExpiredError on a 401 response., get_members() raises SessionExpiredError on a 403 response., test_get_members_raises_on_401(), test_get_members_raises_on_403()

### Community 37 - "Linux Bonus Time Bot Commands"
Cohesion: 0.25
Nodes (6): Choice, Interaction, Autocomplete: return enabled machines whose name contains `current`., Grant bonus minutes to a machine, unlocking if currently locked., Unlock all sessions on the machine.      Args:         hostname: The SSH host to, unlock_session()

### Community 38 - "Members Route Tests"
Cohesion: 0.33
Nodes (6): Tests for the /api/members router., GET /api/members with a valid session cookie returns 200 and a list., GET /api/members without a session cookie returns 401., _session_cookie(), test_get_members_rejects_no_session(), test_get_members_returns_200()

### Community 39 - "Alembic Migration Env"
Cohesion: 0.33
Nodes (5): Alembic environment configuration for database migrations.  Supports both online, Run migrations in 'offline' mode.      This generates SQL for applying migration, Run migrations in 'online' mode.      This connects to an actual database and ap, run_migrations_offline(), run_migrations_online()

### Community 40 - "Cookie Jar Resolution"
Cohesion: 0.33
Nodes (4): CookieJar, RuntimeError, Path, Return (sapisid, cookies_jar). Raises ValueError or RuntimeError on failure.

### Community 41 - "Auth + SAPISIDHASH Generation"
Cohesion: 0.33
Nodes (3): _generate_sapisidhash(), Request, Family Link API client.

### Community 42 - "Member + Usage Queries"
Cohesion: 0.33
Nodes (4): List family members for the authenticated parent., Print usage for all family members., MembersResponse, Response from the members API endpoint.

### Community 43 - "Linux Machines DB Migration"
Cohesion: 0.40
Nodes (4): downgrade(), Add linux_machines and linux_usage_snapshots., Drop linux_machines and linux_usage_snapshots., upgrade()

### Community 44 - "Bonus Minutes DB Migration"
Cohesion: 0.40
Nodes (4): downgrade(), Add bonus_mins column to linux_usage_snapshots., Drop bonus_mins column from linux_usage_snapshots., upgrade()

## Knowledge Gaps
- **22 isolated node(s):** `familylink`, `GitHub Copilot Instructions`, `Release Drafter Config`, `CI Workflow`, `Ruff Lint Workflow` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `FamilyLinkService` connect `Discord Slash Commands` to `Server Config + DB Session`, `Linux Machine ORM Model`, `Linux Usage Snapshot Model`, `Server Lifecycle + Bot Client`, `FastAPI Admin Routes`, `App Management Routes`, `Discord UI Views`, `App Usage Models`, `Member + Usage Queries`, `Discord Apps Command Group`, `API Client Methods`, `Linux Machine Routes`, `Cookie Hot-Reload Tests`, `Cookie Reinit Method`, `Dashboard + Constants`, `FamilyLink Service Tests`, `Bot Usage Commands`?**
  _High betweenness centrality (0.333) - this node is a cross-community bridge._
- **Why does `FamilyLink` connect `API Client Methods` to `Server Config + DB Session`, `CLI Commands`, `API GET Methods`, `Time Limits + Session Errors`, `Server Lifecycle + Bot Client`, `Auth + SAPISIDHASH Generation`, `Member + Usage Queries`, `App Usage Models`, `Cookie Auth Resolution`, `Cookie Reinit Method`, `Unit Client Tests`?**
  _High betweenness centrality (0.141) - this node is a cross-community bridge._
- **Why does `DiscordNotifier` connect `Discord Slash Commands` to `Discord Session Alert Tests`, `Async Services + Linux Poller`, `App Management Routes`, `Discord UI Views`, `App Usage Models`, `Discord Apps Command Group`, `Discord Notification Service`, `Discord Notifier Tests`, `Bot Usage Commands`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `FamilyLinkService` (e.g. with `FamilyLinkBot` and `AppsGroup`) actually correct?**
  _`FamilyLinkService` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `app()` (e.g. with `FastAPI` and `test_client()`) actually correct?**
  _`app()` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `FamilyLink` (e.g. with `CookieResolver` and `AppUsage`) actually correct?**
  _`FamilyLink` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `DiscordNotifier` (e.g. with `FamilyLinkBot` and `AppsGroup`) actually correct?**
  _`DiscordNotifier` has 12 INFERRED edges - model-reasoned connections that need verification._
