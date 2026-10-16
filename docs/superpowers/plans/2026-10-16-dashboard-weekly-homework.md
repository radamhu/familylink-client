# Dashboard Weekly Homework Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat "Homework due" list in the child panel with a Mon–Fri + Weekend weekly table (today highlighted, passed deadlines dimmed).

**Architecture:** Add a never-updated `registered_on` column; a pure `build_week()` function turns a child's rows into a week structure; `_get_child_data` passes that to a new Jinja partial. Pruning keeps rows until Monday of the current week.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, Jinja2, Pico CSS + inline styles, pytest (`python -m pytest`, no `uv`).

**Spec:** `docs/superpowers/specs/2026-10-16-dashboard-weekly-homework-design.md`
Approved mockup: `.superpowers/brainstorm/86970-1792132642/content/week-table.html` (open it for exact look).

## Global Constraints

- Weekend is ONE column (not Sat + Sun).
- Dimmed = `deadline < today`: opacity 0.45, subject struck through. Due today (`deadline == today`): red deadline text.
- Today highlight: blue fill, thick blue border, blue header; only if today is inside the shown week; Sat/Sun highlights the Weekend column.
- Shown week = Mon–Sun week containing the max `date` (last seen) among a child's entries; no entries → no homework section.
- Prune boundary: `deadline < Monday of the week containing today`.
- Notifications in `routers/homework.py` (ntfy on newly created rows) must keep working unchanged.
- `date` keeps "last seen" meaning (upsert still overwrites it); `registered_on` is set on insert only.
- Ruff: Google docstrings, single-quoted strings. Run `ruff check src tests && ruff format src tests` before each commit.
- "today" everywhere comes from one helper `local_today()` (container-local `date.today()`).

## Review Focus

- Entry registered on Sat/Sun: Weekend column only, no duplicate copy (Task 2 test).
- Registered in an earlier week, due after the shown week or on Sat/Sun of it: Weekend column only (Task 2 test).
- Registered in an earlier week, due inside the shown week on a weekday: appears in the deadline day's column (Task 2 test).
- Monday before the scrape (shown week is last week, today is outside it): no highlight, no crash (Task 2 test).
- Re-scrape moves `date` but never `registered_on`; leftovers with both dates and deadline before the shown week are skipped, not crashed on (Tasks 1, 2 tests).

---

### Task 1: `registered_on` column, migration, upsert

**Files:**
- Modify: `src/familylink_server/db/models.py:174-198` (HomeworkEntry)
- Create: `alembic/versions/009_homework_registered_on.py`
- Modify: `src/familylink_server/db/homework.py` (`upsert_homework_entries`)
- Test: `tests/server/test_db_homework.py`

**Interfaces:**
- Produces: `HomeworkEntry.registered_on: Mapped[date]` (non-null). Insert sets it to the `today` argument; refresh leaves it untouched.

- [ ] **Step 1: Write failing tests** in `test_db_homework.py`: `test_upsert_sets_registered_on_on_insert` (insert with today=2026-09-08, assert `registered_on == date(2026,9,8)`); `test_upsert_refresh_keeps_registered_on` (insert today=09-08, upsert again today=09-10; assert `date == 09-10` and `registered_on == 09-08`).
- [ ] **Step 2: Run** `python -m pytest tests/server/test_db_homework.py -v` — expect the new tests FAIL (no attribute `registered_on`).
- [ ] **Step 3: Add** `registered_on: Mapped[date] = mapped_column(Date, nullable=False)` to `HomeworkEntry`; set `registered_on=today` in the insert branch of `upsert_homework_entries` only. Update the docstring (date = last seen, registered_on = first seen). Fix any existing test that constructs `HomeworkEntry(...)` directly by adding `registered_on`.
- [ ] **Step 4: Migration `009`** (`down_revision = '008'`, same file style as `006`): add column nullable, `op.execute('UPDATE homework_entries SET registered_on = date')`, then `op.alter_column(..., nullable=False)`; downgrade drops the column.
- [ ] **Step 5: Run** `python -m pytest tests/server/test_db_homework.py tests/server/test_routers_homework.py -v` — expect PASS.
- [ ] **Step 6: Commit** `feat: store homework registered_on (first seen)`.

### Task 2: Pure week builder

**Files:**
- Create: `src/familylink_server/services/homework_week.py`
- Test: `tests/server/test_homework_week.py`

**Interfaces:**
- Produces (exact names, used by Tasks 3–4):

```python
@dataclass(frozen=True)
class HomeworkCell:
    subject: str
    description: str
    deadline: date
    dimmed: bool        # deadline < today
    due_today: bool     # deadline == today
    to_weekend: bool    # day-column original whose deadline is after the shown week
    is_weekend_copy: bool  # cell lives in the Weekend column (shows a deadline tag)

@dataclass(frozen=True)
class WeekColumn:
    label: str          # 'Mon'..'Fri', 'Weekend'
    day: date | None    # None for Weekend
    is_today: bool
    cells: list[HomeworkCell]

@dataclass(frozen=True)
class HomeworkWeek:
    columns: list[WeekColumn]   # exactly 6: Mon..Fri, Weekend

def week_start(d: date) -> date: ...   # Monday of d's week
def build_week(entries: Sequence[Any], today: date) -> HomeworkWeek | None: ...
```
  `entries` items expose `.subject .description .deadline .date .registered_on` (ORM rows or test stubs).

- [ ] **Step 1: Write failing tests** in `test_homework_week.py`, using `types.SimpleNamespace` stubs and `today = date(2026,10,16)` (Fri; week Mon 10-12). Tests: `test_no_entries_returns_none`; `test_entry_in_registration_day_column` (reg Tue 10-13, deadline Thu 10-15 → Tue cell, `dimmed`); `test_today_column_flagged`; `test_due_today_flag`; `test_later_week_deadline_gets_weekend_copy` (reg Thu, deadline Mon 10-19 → Thu cell `to_weekend=True` + Weekend cell `is_weekend_copy=True`); `test_weekend_registration_has_no_duplicate_copy` (reg Sat 10-17, deadline 10-21 → exactly one Weekend cell); `test_carryover_due_in_shown_week_goes_to_deadline_day` (reg 10-09, deadline Wed 10-14 → Wed column); `test_carryover_due_later_goes_weekend_only`; `test_carryover_due_on_weekend_of_shown_week_goes_weekend`; `test_stale_row_before_week_skipped` (reg and deadline before Monday); `test_monday_before_scrape_keeps_old_week_no_highlight` (today 10-19, all `date`s in 10-12..10-16 → columns days 10-12.., no `is_today` anywhere); `test_saturday_highlights_weekend_column`; `test_rollover_uses_last_seen_date` (row reg 10-16 but `date`=10-19, today=10-19 → shown week starts 10-19, row in Mon column as carried-over deadline day).
- [ ] **Step 2: Run** `python -m pytest tests/server/test_homework_week.py -v` — expect FAIL (module missing).
- [ ] **Step 3: Implement** per the placement rules in spec Decision 3; within a cell list sort by subject. Pure function, no I/O.
- [ ] **Step 4: Run** the same command — expect PASS. Run `ruff check src tests`.
- [ ] **Step 5: Commit** `feat: pure weekly homework builder`.

### Task 3: DB queries, prune boundary, shared `local_today`

**Files:**
- Modify: `src/familylink_server/db/homework.py` (replace `get_upcoming_homework`, change `prune_expired_homework`, add `local_today`)
- Modify: `src/familylink_server/routers/homework.py:97-113` (use `local_today()`)
- Test: `tests/server/test_db_homework.py`, `tests/server/test_routers_homework.py`

**Interfaces:**
- Consumes: `week_start` from Task 2.
- Produces: `def local_today() -> date`; `async def get_child_homework(session, child_id: str) -> list[HomeworkEntry]` (all rows for the child, ordered by `deadline, subject`). `prune_expired_homework(session, child_id, today)` keeps its signature but deletes `deadline < week_start(today)`. `get_upcoming_homework` is removed.

- [ ] **Step 1: Update tests:** rewrite `test_prune_expired_homework_deletes_past_deadline_only` for the Monday boundary (today Thu 2026-10-15: deadline 10-11 deleted; 10-12 and 10-14 kept). Replace the two `get_upcoming_homework` tests with `test_get_child_homework_returns_all_rows_for_child_only` and ordering by deadline then subject. In `test_routers_homework.py` patch `familylink_server.routers.homework.local_today` where tests pinned `date.today()`.
- [ ] **Step 2: Run** `python -m pytest tests/server/test_db_homework.py tests/server/test_routers_homework.py -v` — expect FAIL.
- [ ] **Step 3: Implement** the three changes above.
- [ ] **Step 4: Run** same command — expect PASS.
- [ ] **Step 5: Commit** `feat: keep homework rows through the current week`.

### Task 4: Dashboard integration and template

**Files:**
- Modify: `src/familylink_server/routers/dashboard.py:31,93-105` (use `local_today`, `get_child_homework`, `build_week`; `'homework'` becomes `HomeworkWeek | None`)
- Create: `src/familylink_server/templates/partials/homework_week.html`
- Modify: `src/familylink_server/templates/partials/child_expanded.html:67-77` (replace the list with `{% include 'partials/homework_week.html' %}` guarded by `{% if child.homework %}`)
- Modify: `tests/server/test_routers_dashboard.py:247-310` and any other test touching `child.homework`
- Modify: `docs/ekreta.md` (one paragraph describing the weekly table)

**Interfaces:**
- Consumes: `build_week`, `HomeworkWeek`, `get_child_homework`, `local_today`.

- [ ] **Step 1: Update/add tests** in `test_routers_dashboard.py` (existing tests mock `session.execute` with `MagicMock` rows — set `.date`, `.registered_on`, `.deadline`, `.subject`, `.description` on them; patch `familylink_server.routers.dashboard.local_today` to a fixed Friday): `test_child_detail_renders_week_table_with_today_column` (response contains `Weekend` and the subject), `test_child_detail_dims_passed_deadline` (assert the dimmed marker class, e.g. `hw-past`), keep `test_child_detail_hides_homework_section_when_none_upcoming` (no rows → no `Weekend` header).
- [ ] **Step 2: Run** `python -m pytest tests/server/test_routers_dashboard.py -v` — expect FAIL.
- [ ] **Step 3: Implement** the partial per the mockup: 6 columns (`table-layout:fixed`), classes `hw-today`, `hw-past`, `hw-soon` (red deadline), weekend column dashed amber with deadline tag on `is_weekend_copy` cells, "→ weekend" hint when `to_weekend`. Below ~640px the table collapses to a stacked day-by-day list (CSS-only). Grep for other readers of `child.homework` / `hw.` in templates and update them.
- [ ] **Step 4: Run** `python -m pytest` (full suite) — expect PASS; `ruff check src tests && ruff format src tests`.
- [ ] **Step 5: Visual check:** run `uvicorn familylink_server.main:app --reload` with seeded rows (or render the partial via a small script) and compare with the mockup in both states A and B; report anything off.
- [ ] **Step 6: Run** `graphify update .`; **commit** `feat: weekly homework table on dashboard`.
