# eKRÉTA homework: second source + deadline-based display — design

## Purpose

Today's homework pipeline (`docs/superpowers/specs/2026-09-08-ekreta-homework-migration-design.md`)
scrapes only the Órarend (timetable) page's homework-icon lessons for
"today", and the dashboard shows only that day's entries. Two gaps:

- Homework can also live on `Tanulo/TanuloHaziFeladat` ("Házi
  feladatok" — homework list page) instead of, or in addition to,
  Órarend. Some assignments never carry a calendar icon and only show
  up there.
- A homework item is relevant to a parent for its whole open window,
  not just the day it was assigned — the dashboard should show it
  every day until its deadline passes, not just on scrape day.

This design scrapes both pages, merges/dedupes what they report about
the same assignment, and switches the dashboard from "today's
homework" to "homework due" filtered by a real `deadline` field.

## Non-goals

- No "submitted/done" completion tracking — out of scope, list page's
  status column (if any) is not scraped.
- No historical view of expired homework — once `deadline < today` a
  row is pruned, not archived.
- No change to `ekreta_credentials` / scraper deployment shape.

## Data model change

`homework_entries` gains a `deadline: Date NOT NULL` column
(migration `006`, `down_revision='005'`). A unique constraint
`uq_homework_entries_child_subject_deadline` on `(child_id, subject,
deadline)` becomes the identity of "one homework item" — this is what
lets the same assignment, re-scraped from either page or on a later
day while still open, collapse into one row instead of duplicating.

The existing `date` column keeps its current type/nullability
(informational "last seen/assigned" date); no query still groups by
it. `fetched_at` is unchanged.

## `db/homework.py`

Replaces the day-bucket functions with identity-based ones:

- `upsert_homework_entries(session, child_id, entries)` — entries are
  `{'subject', 'deadline', 'description'}`. Uses
  `sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_update()`
  on `(child_id, subject, deadline)`, updating `description` and
  `fetched_at`. A still-open item scraped again just refreshes in
  place.
- `prune_expired_homework(session, child_id, today)` — deletes rows
  where `deadline < today` for that kid.
- `get_upcoming_homework(session, child_id, today)` — rows where
  `deadline >= today`, ordered by `(deadline, subject)`.

`list_ekreta_credentials` is unchanged.

## Ingest endpoint (`routers/homework.py`)

`HomeworkIngestIn` drops the top-level `date` field — a POST is no
longer "this batch is for day X"; each entry already carries its own
`deadline`. New shape:

```
POST /internal/ekreta/homework
{
  "child_id": "child1",
  "entries": [
    {"subject": "Matek", "teacher": "...", "deadline": "2026-09-10",
     "text": "...", "attachments": [...]}
  ]
}
```

`HomeworkEntryIn.deadline` becomes a required `date` (was a free-text
string folded into the description). `_format_description` drops the
"Deadline: ..." line it used to synthesize — the deadline is now a
real column, rendered separately by the dashboard, not duplicated in
free text.

On ingest: `upsert_homework_entries(session, child_id, entries)`, then
`prune_expired_homework(session, child_id, date.today())`, then
commit. Auth/shared-secret behavior (`X-Api-Key`, fail-closed) is
unchanged.

## Scraper (`ekreta-scraper/src/kreta_client.py`)

### Two source scrapes, merged

`fetch_homework(page, kid)` becomes:

1. `_fetch_from_orarend(page, kid) -> list[dict]` — today's existing
   dialog-click flow, unchanged selectors/behavior, wrapped in
   try/except so a failure here doesn't block the second source.
2. `_fetch_from_haza_feladatok(page, kid) -> list[dict]` — new: after
   login, navigate to the "Házi feladatok" page (menu item, same
   pattern as the existing `Órarend` click), read each row of the
   list table: subject, teacher (if present), the `"Házi feladat
   határideje"` column as the deadline, description text, attachments
   (if the list exposes them — otherwise empty). Also wrapped in
   try/except for source-level isolation.

   **Selectors for this page are unconfirmed** — unlike Órarend's
   selectors (verified against the live site when that scraper was
   built), this page has not been inspected live. The implementation
   plan must include a step to verify actual markup/selectors against
   the real site (or a saved HTML sample) before this ships; initial
   selectors are a best-effort guess subject to that check.
3. Merge: build a dict keyed by `(subject, parsed_deadline)`; when
   both sources report the same key, keep the entry with the longer
   `text` (richer detail — Órarend's dialog tends to have more) and
   the union of `attachments`.
4. Filter: drop any merged entry whose `deadline < today` before
   returning — the scraper only ever reports current/upcoming
   homework (per approved answer: filter at the scraper, keep the
   server a dumb store).

### Shared Hungarian-date parsing

Both sources render dates as Hungarian-locale text but plausibly in
different formats (Órarend's dialog footer text vs. the list page's
table cell). Add `_parse_hun_date(raw: str) -> date` used by both
source parsers before entries are merged/compared — comparisons and
the `deadline >= today` filter operate on parsed `date` objects, never
on raw strings. An entry whose deadline fails to parse is logged and
dropped (does not fail the whole kid).

### `parse_homework_entry`

Extended to require a parsed `deadline: date` (previously a stripped
string). Still returns the same dict shape plus `deadline`.

## `api_client.py` / `main.py`

`post_homework(api_url, token, child_id, entries)` — drops the `day`
parameter (no longer meaningful now the batch isn't day-scoped).
`main.run()`'s `post_fn` signature shrinks to match. `today` parameter
on `run()` is no longer needed for posting, but scraping itself still
needs "today" for the Órarend weekday-column lookup and the
`deadline >= today` filter — that stays sourced from `date.today()`
inside `fetch_homework`, not threaded through `run()`.

## Dashboard (`dashboard.py`, `child_expanded.html`)

`_get_child_data` calls `get_upcoming_homework(session, child.user_id,
today)` instead of `get_homework_for_day`. Returned dict:

```python
homework = [
    {'subject': h.subject, 'description': h.description,
     'deadline': h.deadline.isoformat()}
    for h in homework_rows
]
```

Template heading changes from "Homework today" to "Homework due";
each row shows its deadline alongside subject/description. Empty-list
behavior unchanged (renders nothing, no error state).

## Error handling

- Per-source scrape failure (nav/selector change on either page):
  caught, logged, that source contributes nothing — the other source's
  results still get merged and posted. Extends the existing per-kid
  isolation to per-source-within-a-kid.
- Deadline parse failure on one entry: logged, that entry dropped,
  rest of the batch still posted.
- Duplicate/re-scrape of a still-open item: handled by the DB upsert,
  not scraper-side dedup against prior runs (scraper has no memory
  between runs).
- Ingest auth/shared-secret behavior: unchanged from the existing
  fail-closed design.

## Testing

- `kreta_client`: unit tests for `_parse_hun_date` (both known
  formats), for the merge function (same-key entries from both
  sources collapse, richer `text` wins, attachments union), for the
  `deadline >= today` filter, and for per-source try/except isolation
  (one source raising doesn't stop the other from contributing).
- `db/homework.py`: `upsert_homework_entries` inserts new / updates
  existing on the same `(child_id, subject, deadline)` key;
  `prune_expired_homework` deletes only `deadline < today` rows;
  `get_upcoming_homework` filters and orders correctly.
- `routers/homework.py`: update existing ingest tests for the new
  payload shape (no top-level `date`, entries carry `deadline`);
  assert upsert+prune are both called.
- Dashboard: existing test updated to seed a future-deadline entry and
  assert it renders; new test seeds a past-deadline entry and asserts
  it does **not** render.

## Deployment

No new env vars or services. Migration `006` ships in the same release
as the router/scraper changes (breaking payload change to an endpoint
that isn't yet carrying real production traffic today).
