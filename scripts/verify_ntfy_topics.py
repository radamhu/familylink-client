#!/usr/bin/env python
"""One-off Playwright smoke test: confirms every configured kid's ntfy topic
is reachable and renders a live push in the ntfy web UI.

Not part of the pytest suite — this hits the real, self-hosted ntfy server
configured via NTFY_BASE_URL/NTFY_TOPICS. Run manually after configuring
those env vars (see README "Verifying ntfy setup"):

    pip install playwright && playwright install chromium
    python scripts/verify_ntfy_topics.py
"""

from __future__ import annotations

import asyncio
import sys

from playwright.async_api import Browser, async_playwright

from familylink_server.config import settings
from familylink_server.services.ntfy_notifier import NtfyNotifier


async def _check_one(
    browser: Browser, notifier: NtfyNotifier, child_id: str, topic: str
) -> bool:
    """Open the topic's live web view, push a test message, confirm it renders."""
    page = await browser.new_page()
    marker = f'verify-{child_id}'
    try:
        await page.goto(f'{settings.ntfy_base_url}/{topic}', wait_until='networkidle')
        await notifier.send(child_id, 'Verify', marker)
        await page.get_by_text(marker).wait_for(timeout=15_000)
        await page.screenshot(path=f'/tmp/ntfy-verify-{child_id}.png')
        print(f'OK   {child_id:12s} topic={topic}')
        return True
    except Exception as exc:
        print(f'FAIL {child_id:12s} topic={topic}  ({exc})')
        return False
    finally:
        await page.close()


async def main() -> int:
    topics = settings.ntfy_topics_parsed
    if not topics:
        print('NTFY_TOPICS is empty — nothing to verify.')
        return 1

    notifier = NtfyNotifier(topics, base_url=settings.ntfy_base_url)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            results = await asyncio.gather(
                *[
                    _check_one(browser, notifier, child_id, topic)
                    for child_id, topic in topics.items()
                ]
            )
        finally:
            await browser.close()

    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
