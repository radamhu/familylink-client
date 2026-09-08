import sys
from datetime import date, datetime

from config import Kid

INSTITUTION_SEARCH_URL = "https://intezmenykereso.e-kreta.hu/"

_HAZA_FELADATOK_DEADLINE_HEADER = "Házi feladat határideje"
_HUN_DATE_FORMATS = ("%Y. %m. %d.", "%Y.%m.%d.", "%Y-%m-%d")


class KretaClientError(Exception):
    """Raised when scraping fails for a kid (login, navigation, or no school that day)."""


def today_weekday_index(today: date) -> int:
    """Monday=0 .. Friday=4, matching Órarend's fixed 5-column week layout."""
    weekday = today.weekday()
    if weekday > 4:
        raise KretaClientError(f"No school on weekday index {weekday} (weekend)")
    return weekday


def _parse_hun_date(raw: str) -> date:
    """Parse a Hungarian-locale eKRÉTA date string into a date.

    Tries the format seen on Órarend's dialog footer ("2026. 09. 09."), a
    plausible Házi Feladatok list-page format without spaces
    ("2026.09.09."), and plain ISO as a fallback.
    """
    text = raw.strip()
    for fmt in _HUN_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise KretaClientError(f"Unparseable deadline date: {raw!r}")


def parse_homework_entry(raw: dict) -> dict:
    """Normalize a raw scraped homework dict into the spec's entry shape."""
    deadline = _parse_hun_date(raw.get("deadline", ""))
    return {
        "subject": raw.get("subject", "").strip(),
        "teacher": raw.get("teacher", "").strip(),
        "deadline": deadline.isoformat(),
        "text": raw.get("text", "").strip(),
        "attachments": raw.get("attachments") or [],
    }


def _merge_homework_entries(entries: list[dict]) -> list[dict]:
    """Collapse same-(subject, deadline) entries from both sources into one.

    Keeps the richer `text`, unions `attachments`, fills in `teacher` from
    whichever entry has one.
    """
    merged: dict[tuple[str, str], dict] = {}
    for entry in entries:
        key = (entry["subject"], entry["deadline"])
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(entry)
            continue
        if len(entry["text"]) > len(existing["text"]):
            existing["text"] = entry["text"]
        if not existing["teacher"]:
            existing["teacher"] = entry["teacher"]
        existing["attachments"] = sorted(
            set(existing["attachments"]) | set(entry["attachments"])
        )
    return list(merged.values())


def _filter_upcoming(entries: list[dict], today: date) -> list[dict]:
    """Keep only entries whose deadline hasn't passed yet."""
    return [e for e in entries if date.fromisoformat(e["deadline"]) >= today]


def _login(page, kid: Kid) -> None:
    """Institution search + credential login, shared by both scrape sources."""
    page.goto(INSTITUTION_SEARCH_URL, wait_until="networkidle")
    page.locator("#institute-selector-auto-complete-input-id").fill(
        kid.institution_code
    )
    page.locator("li").first.wait_for()
    page.locator("li").first.click()
    page.get_by_role("button", name="TOVÁBB A KRÉTA OLDALÁRA").click()
    page.wait_for_load_state("networkidle")

    page.locator("#UserName").fill(kid.username)
    page.locator("#Password").fill(kid.password)
    page.get_by_role("button", name="Bejelentkezés").click()
    page.wait_for_load_state("networkidle")


def _scrape_orarend(page, kid: Kid) -> list[dict]:
    """Scrape today's homework-icon lessons off the Órarend week view.

    Selectors confirmed against the live site (2026-09-08, Brassó Utcai
    Általános Iskola / 035120): Órarend is a FullCalendar week view where
    each weekday is a single `<td>` containing one `.fc-event-container`
    with one `<a class="fc-time-grid-event">` per lesson period that day; a
    lesson with homework carries an `i.hasCalendarIcon` (house) icon inside
    it. Clicking a lesson opens a Kendo UI modal dialog with two tabs,
    "Óra adatai" (lesson data) and "Házi feladat" (homework) — both tab
    panels exist in the DOM at once, only their visibility toggles, so
    fields from either tab can be read regardless of which tab is currently
    showing.
    """
    weekday_index = today_weekday_index(date.today())

    page.get_by_text("Elektronikus ellenőrzőkönyv").click()
    page.wait_for_load_state("networkidle")
    page.get_by_text("Órarend", exact=True).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("td:has(.fc-event-container)")

    event_columns = page.locator("td:has(.fc-event-container)")
    if event_columns.count() <= weekday_index:
        # No week grid rendered for today (e.g. holiday view) — nothing due.
        return []
    today_column = event_columns.nth(weekday_index)
    house_lessons = today_column.locator("a.fc-time-grid-event:has(i.hasCalendarIcon)")

    entries: list[dict] = []
    for i in range(house_lessons.count()):
        house_lessons.nth(i).click()
        page.wait_for_selector("[role=dialog]")
        # The dialog's Kendo TabStrip widget needs a moment to finish
        # binding its click handlers after the dialog DOM appears —
        # clicking the tab immediately on dialog-open is a no-op.
        page.wait_for_timeout(500)
        page.get_by_text("Házi feladat", exact=True).first.click()
        page.wait_for_selector(".panel-body")

        raw = {
            "subject": page.locator('[displayfor="Targy"]').inner_text(),
            "teacher": page.locator('[displayfor="Tanar"]').inner_text(),
            "deadline": page.locator(".panel-footer")
            .first.inner_text()
            .replace("Határidő:", ""),
            "text": page.locator(".panel-body").first.inner_text(),
            "attachments": [
                row.locator("td").first.inner_text()
                for row in page.locator(
                    "#HFCsatolmanyGrid tbody tr:not(.k-no-data)"
                ).all()
            ],
        }
        try:
            entries.append(parse_homework_entry(raw))
        except KretaClientError as exc:
            print(  # noqa: T201
                f"[WARN] skipping unparseable orarend lesson for {kid.child_id}: {exc}",
                file=sys.stderr,
            )

        page.locator("#BtnCancel").click()
        page.wait_for_timeout(300)

    return entries


def _column_index(header_cells, header_text: str) -> int | None:
    """Find a table column's index by its header text."""
    for i, cell in enumerate(header_cells):
        if cell.inner_text().strip() == header_text:
            return i
    return None


def _scrape_haza_feladatok(page, kid: Kid) -> list[dict]:
    """Scrape the Tanulo/TanuloHaziFeladat homework list table.

    Unlike Órarend's selectors (confirmed against the live site above),
    this page has not been inspected live — selectors here are a
    best-effort guess and must be verified against the real site (or a
    saved HTML sample) before this ships. The deadline column is located
    by its known header text rather than a hardcoded index, to survive
    column-order differences from whatever the real markup turns out to
    be; other columns fall back to empty values if not found.
    """
    page.get_by_text("Elektronikus ellenőrzőkönyv").click()
    page.wait_for_load_state("networkidle")
    page.get_by_text("Házi feladatok", exact=True).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("table tbody tr")

    header_cells = page.locator("table thead th").all()
    subject_idx = _column_index(header_cells, "Tantárgy")
    deadline_idx = _column_index(header_cells, _HAZA_FELADATOK_DEADLINE_HEADER)
    text_idx = _column_index(header_cells, "Feladat leírása")
    teacher_idx = _column_index(header_cells, "Tanár")
    if deadline_idx is None or subject_idx is None:
        raise KretaClientError("Házi feladatok table missing expected columns")

    entries: list[dict] = []
    for row in page.locator("table tbody tr").all():
        cells = row.locator("td").all()
        raw = {
            "subject": cells[subject_idx].inner_text(),
            "teacher": cells[teacher_idx].inner_text() if teacher_idx is not None else "",
            "deadline": cells[deadline_idx].inner_text(),
            "text": cells[text_idx].inner_text() if text_idx is not None else "",
            "attachments": [],
        }
        try:
            entries.append(parse_homework_entry(raw))
        except KretaClientError as exc:
            print(  # noqa: T201
                f"[WARN] skipping unparseable haza_feladatok row for "
                f"{kid.child_id}: {exc}",
                file=sys.stderr,
            )

    return entries


def fetch_homework(page, kid: Kid) -> list[dict]:
    """Full login-to-scrape flow for one kid, merging both homework sources.

    Logs in once, then scrapes Órarend and Házi Feladatok independently —
    one source failing (nav error, markup change, weekend with no Órarend
    view) does not drop the other source's results. Same-(subject,
    deadline) entries from both sources are merged into one; the result is
    filtered to not-yet-due items before being returned for posting.
    """
    _login(page, kid)

    entries: list[dict] = []
    try:
        entries += _scrape_orarend(page, kid)
    except Exception as exc:
        print(  # noqa: T201
            f"[WARN] orarend scrape failed for {kid.child_id}: {exc}", file=sys.stderr
        )
    try:
        entries += _scrape_haza_feladatok(page, kid)
    except Exception as exc:
        print(  # noqa: T201
            f"[WARN] haza_feladatok scrape failed for {kid.child_id}: {exc}",
            file=sys.stderr,
        )

    merged = _merge_homework_entries(entries)
    return _filter_upcoming(merged, date.today())
