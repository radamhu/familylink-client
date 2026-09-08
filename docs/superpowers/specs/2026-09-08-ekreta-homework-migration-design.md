# eKRÉTA homework migration — design

## Purpose

Fold the standalone `ekreta` repo (Playwright scraper for the Hungarian
eKRÉTA school portal + its own tiny FastAPI dashboard, flat-JSON storage,
2-service docker-compose) into `familylink-client`, so homework shows up
next to each kid's app/device/Linux data on the existing dashboard, and
there is one repo/one deploy instead of two.

## Non-goals

- No historical backfill — the ~30 days of JSON under `ekreta/data/` are
  not migrated. The new table starts empty.
- No standalone eKRÉTA web UI — the current `web/` app is retired; its
  only surviving role is display, and that display moves into
  `familylink_server`'s dashboard.
- The old `ekreta` repo is deleted once this works, not archived.

## Architecture

### New DB tables (Alembic migration, `familylink-client` DB)

- `ekreta_credentials` — `child_id` (matches the Google Family Link
  `user_id` used by `AppConfig`/`LinuxMachine`), `username`, `password`,
  `institution_code`.
- `homework_entries` — `child_id`, `date`, `subject`, `description`,
  `fetched_at`.

### New router: `src/familylink_server/routers/homework.py`

Two internal endpoints, protected by a shared-secret header
(`EKRETA_INGEST_TOKEN`), no browser session involved:

- `GET /internal/ekreta/credentials` — returns the per-kid login list
  from `ekreta_credentials`, for the scraper to consume.
- `POST /internal/ekreta/homework` — body `{child_id, date, entries:
  [...]}`; upserts entries for that kid/date, then deletes that kid's
  rows older than `RETENTION_DAYS`.

No new public page. `_get_child_data()` in `dashboard.py` gains a
`homework` block (query `homework_entries` for `child_id`), rendered in
`dashboard.html` / `partials/child_expanded.html` next to the existing
apps/devices/Linux sections.

### Scraper stays a separate runner: `ekreta-scraper/`

New top-level directory in `familylink-client`, same shape as today's
`ekreta/scraper/` (own Dockerfile with Playwright/Chromium, own
requirements, own cron entrypoint), added as its own service in
`familylink-client`'s `docker-compose.yml` — no ports exposed, internal
network only, same pattern as `cookie-refresher`. It holds no
credentials itself; it fetches them from the API each run.

## Data flow

1. **Config**: a kid's eKRÉTA username/password/institution_code go
   into `ekreta_credentials`, keyed by `child_id`. (Seeding path —
   manual insert or a small admin form — is an implementation-plan
   detail, not fixed here.)
2. **Scrape cycle** (cron in `ekreta-scraper`, e.g. weekdays 06:00,
   matching today's default):
   - `GET /internal/ekreta/credentials` (shared-secret header) → list
     of `{child_id, username, password, institution_code}`.
   - For each kid: Playwright login + scrape, reusing the existing
     `kreta_client.py` logic, with the existing per-kid failure
     isolation (one kid's failure doesn't block the others).
   - `POST /internal/ekreta/homework` per kid with that day's entries.
3. **Server on ingest**: upserts entries for `child_id`/date, prunes
   rows for that kid older than `RETENTION_DAYS`.
4. **Dashboard render**: per-kid card queries `homework_entries` for
   `child_id` and shows it alongside apps/devices/Linux data.

## Error handling

- **Scraper→API unreachable**: log and retry on the next cron tick;
  per-kid isolation preserved.
- **Bad/missing shared secret**: both internal endpoints return `401`;
  scraper logs and skips without retry-storming.
- **Playwright login failure** (bad creds, site markup change): caught
  per-kid, skip that kid, continue the others — same as today's
  `kreta_client.py` behavior. No partial-day POST for that kid.
- **Empty/missing homework for a kid**: dashboard renders an empty
  state, not an error — same convention as `top5`/`linux_rows`
  defaulting to `[]`.

## Testing

- Unit tests for `homework.py` (ingest auth, upsert, prune-on-ingest)
  under `tests/server/`, following existing router test conventions.
- `alembic upgrade head` exercised against a test DB.
- Scraper's existing tests (`test_kreta_client.py`, `test_config.py`,
  `test_main.py`) move into `ekreta-scraper/`; `storage.py`'s JSON-write
  path is replaced by an HTTP-post path and tested against a mocked
  HTTP client instead of `tmp_path` JSON files.
- Dashboard integration test: seed `homework_entries`, hit `/`, assert
  the homework block renders.

## Deployment

- `ekreta-scraper` service added to `familylink-client`'s
  `docker-compose.yml`: env `FAMILYLINK_API_URL`, `EKRETA_INGEST_TOKEN`,
  `CRON_SCHEDULE`; no ports; internal network only.
- `EKRETA_INGEST_TOKEN` added to the `web` service's env and to
  `.env.example`.
- The Alembic migration ships in the same release as the router.

## Repo lifecycle

Once the above is implemented and verified working inside
`familylink-client`, the standalone `ekreta` git repo/directory is
deleted — no archive, no ongoing parallel maintenance.
