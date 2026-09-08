"""Wire together config, api_client, and kreta_client to scrape and post homework."""

import sys
from collections.abc import Callable
from datetime import date

from api_client import post_homework
from config import Kid, fetch_kids


def run(
    kids: list[Kid],
    api_url: str,
    token: str,
    fetch_fn: Callable[[Kid], list[dict]],
    post_fn: Callable[[str, str, str, date, list[dict]], None] = post_homework,
    today: date | None = None,
) -> int:
    """Scrape homework for each kid and POST to the API.

    On failure for any kid, log to stderr and skip posting for that kid,
    returning 1 to signal partial failure.
    """
    today = today or date.today()
    any_failed = False

    for kid in kids:
        try:
            entries = fetch_fn(kid)
        except Exception as exc:
            print(f'[ERROR] {kid.child_id}: {exc}', file=sys.stderr)  # noqa: T201
            any_failed = True
            continue

        try:
            post_fn(api_url, token, kid.child_id, today, entries)
        except Exception as exc:
            print(f'[ERROR] {kid.child_id}: {exc}', file=sys.stderr)  # noqa: T201
            any_failed = True
            continue

    return 1 if any_failed else 0


def main() -> int:
    """Launch browser, fetch homework for all kids, and post results to API."""
    import os

    from kreta_client import fetch_homework
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    api_url = os.environ['FAMILYLINK_API_URL']
    token = os.environ['EKRETA_INGEST_TOKEN']
    kids = fetch_kids(api_url, token)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def fetch_fn(kid: Kid) -> list[dict]:
            for attempt in range(2):
                context = browser.new_context()
                try:
                    return fetch_homework(context.new_page(), kid)
                except PlaywrightTimeoutError:
                    if attempt == 1:
                        raise
                finally:
                    context.close()

        exit_code = run(kids, api_url, token, fetch_fn)
        browser.close()

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
