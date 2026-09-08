from datetime import date

from config import Kid

INSTITUTION_SEARCH_URL = "https://intezmenykereso.e-kreta.hu/"


class KretaClientError(Exception):
    """Raised when scraping fails for a kid (login, navigation, or no school that day)."""


def today_weekday_index(today: date) -> int:
    """Monday=0 .. Friday=4, matching Órarend's fixed 5-column week layout."""
    weekday = today.weekday()
    if weekday > 4:
        raise KretaClientError(f"No school on weekday index {weekday} (weekend)")
    return weekday


def parse_homework_entry(raw: dict) -> dict:
    """Normalize a raw scraped homework dict into the spec's entry shape."""
    return {
        "subject": raw.get("subject", "").strip(),
        "teacher": raw.get("teacher", "").strip(),
        "deadline": raw.get("deadline", "").strip(),
        "text": raw.get("text", "").strip(),
        "attachments": raw.get("attachments") or [],
    }


def fetch_homework(page, kid: Kid) -> list[dict]:
    """Full login-to-scrape flow for one kid.

    `page` is a playwright.sync_api.Page from a fresh BrowserContext.
    Selectors below are confirmed against the live site (2026-09-08,
    Brassó Utcai Általános Iskola / 035120): Órarend is a FullCalendar
    week view where each weekday is a single `<td>` containing one
    `.fc-event-container` with one `<a class="fc-time-grid-event">` per
    lesson period that day; a lesson with homework carries an
    `i.hasCalendarIcon` (house) icon inside it. Clicking a lesson opens a
    Kendo UI modal dialog with two tabs, "Óra adatai" (lesson data) and
    "Házi feladat" (homework) — both tab panels exist in the DOM at once,
    only their visibility toggles, so fields from either tab can be read
    regardless of which tab is currently showing.
    """
    weekday_index = today_weekday_index(date.today())

    page.goto(INSTITUTION_SEARCH_URL, wait_until="networkidle")
    page.locator("#institute-selector-auto-complete-input-id").fill(kid.institution_code)
    page.locator("li").first.wait_for()
    page.locator("li").first.click()
    page.get_by_role("button", name="TOVÁBB A KRÉTA OLDALÁRA").click()
    page.wait_for_load_state("networkidle")

    page.locator("#UserName").fill(kid.username)
    page.locator("#Password").fill(kid.password)
    page.get_by_role("button", name="Bejelentkezés").click()
    page.wait_for_load_state("networkidle")

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
            "deadline": page.locator(".panel-footer").first.inner_text().replace("Határidő:", ""),
            "text": page.locator(".panel-body").first.inner_text(),
            "attachments": [
                row.locator("td").first.inner_text()
                for row in page.locator("#HFCsatolmanyGrid tbody tr:not(.k-no-data)").all()
            ],
        }
        entries.append(parse_homework_entry(raw))

        page.locator("#BtnCancel").click()
        page.wait_for_timeout(300)

    return entries
