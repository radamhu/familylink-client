# Dashboard weekly homework table — design

## Intent

Parents currently see eKRÉTA homework on the dashboard as a flat list sorted by
deadline (`child_expanded.html`, "Homework due"). They cannot tell *when* an item
was assigned or see the shape of the week. Replace the list with a weekly table:
one column per school day, homework shown on the day it was registered, today
highlighted, finished items dimmed.

Approved visual mockup: `.superpowers/brainstorm/86970-1792132642/content/week-table.html`
(states A: Friday of a week, B: Monday after the new week's first scrape).

## Goals

- Per child, a Mon–Fri table plus one narrow "Weekend" column for the current week.
- Entry appears in the column of the day it was first registered (first seen by the scraper).
- Today's column is highlighted (blue fill, thick border, blue header).
- Entries whose deadline is in a **later week** also appear (as a copy) in the single
  Weekend column, tagged with the deadline date. The original stays in its day column
  with a small "→ weekend" hint in its deadline line.
- Entries with a passed deadline stay visible for the rest of the week, dimmed
  (45% opacity, subject struck through).
- Entry due today: red deadline text.
- When the first entry of a new week appears, the table switches to the new week.
  Between weeks (Fri–Sun, Monday before the 06:00 scrape) the old week stays.

## Non-goals / anti-goals

- No new scraping, no change to the scraper or ingest payload. Dashboard stays DB-only.
- Weekend is **not** two columns (Sat + Sun). One simple column.
- No history browsing of past weeks, no editing/checking-off homework.
- Do not break the notification path (`ingest_homework` ntfy on genuinely new entries).

## Facts about current code the builder must know

- `HomeworkEntry` (`db/models.py`): `date`, `deadline`, `subject`, `description`,
  `fetched_at`; unique `(child_id, subject, deadline)`.
- `upsert_homework_entries` (`db/homework.py`) **overwrites `date` with today on every
  re-scrape** of a still-open item. So `date` currently means "last seen", not
  "registered". The scraper reports all open homework each run (deadline >= today).
- `prune_expired_homework` deletes rows with `deadline < today` on every ingest.
- Scraper runs 06:00 Mon–Fri (+ once at container start); none on weekends.
- Dashboard data comes from `_get_child_data` in `routers/dashboard.py`; `date.today()` is used for "today".
- Styling is Pico CSS plus inline grey styles in `partials/child_expanded.html`.

## Decisions

1. **New column `registered_on` (Date)** on `homework_entries`, set only on insert,
   never updated. Alembic migration backfills it from `date`. `date` keeps its current
   "last seen" meaning and drives week rollover.
2. **Shown week** per child = Mon–Sun week containing the most recent `date`
   (last-seen) among that child's entries. No entries → no table (no section).
3. **Placement** within the shown week:
   - `registered_on` in the shown week → that day's column (Sat/Sun registration → Weekend column).
   - `registered_on` before the shown week (carried over) and `deadline` inside the shown
     week → the deadline day's column.
   - `deadline` after the shown week → also a copy in the Weekend column, tagged with deadline date.
4. **Pruning** changes from `deadline < today` to `deadline < Monday of the current week`
   (current week = week containing today), so past days of the current week survive.
5. **Dimmed** = `deadline < today`. **Due today** = `deadline == today`.
6. Today highlight applies only if today lies in the shown week; on Sat/Sun the Weekend
   column is highlighted instead.
7. Table is rendered server-side in Jinja from week-structured data built in
   `_get_child_data` (pure function so it is unit-testable). On narrow screens the
   table collapses to a stacked day-by-day list.

## Calls made by me (not discussed with the user)

- Red "due today" text and the phone stacked layout (user was shown both and approved the mockup).
- `registered_on` column design, shown-week rule, carry-over placement, Weekend highlight on Sat/Sun.
- Dashboard language/labels: English day abbreviations in the mockup; builder may use Hungarian (H K Sze Cs P) if the rest of the UI is Hungarian.

Added after builder check (all my calls):

- **Timezone:** keep the existing `date.today()` convention (container local time). Builder
  should route dashboard, ingest and prune through one shared `today()` helper so they agree.
- **Carry-over edge cases:** item registered before the shown week and due after it, or due
  on Sat/Sun of the shown week → Weekend column only (tagged with deadline), no day column.
- **Backfill is approximate:** existing rows get `registered_on = date` (last seen), so on
  first deploy current items cluster in the latest day. Accepted one-time artifact.
- **Prune dependents:** ntfy notifications key off newly *created* rows only, so they are
  unaffected. Any other consumer of `get_upcoming_homework` must filter `deadline >= today`
  at the query site, since past-deadline rows now survive until Monday.
- **Empty week:** no entries → homework section hidden, no empty-state table.

## Left to the builder

- Exact CSS (keep to the existing inline-grey/Pico look), responsive breakpoint.
- Pure-function shape for week building, test layout.
- Migration revision numbering (follow existing `alembic/versions/`).
- Tests: week builder (rollover, carry-over, weekend copy, dimming, Sat/Sun today), upsert
  keeps `registered_on`, prune boundary, dashboard render.
