"""Sidecar: headless Chrome cookie refresher service."""

import asyncio
import base64
import logging
import os

from fastapi import FastAPI, HTTPException

logger = logging.getLogger(__name__)

app = FastAPI(title='cookie-refresher')


def _to_netscape(cookies: list[dict]) -> str:
    """Convert Playwright cookie dicts to Netscape cookies.txt format."""
    lines = ['# Netscape HTTP Cookie File']
    for c in cookies:
        sub = 'TRUE' if c['domain'].startswith('.') else 'FALSE'
        secure = 'TRUE' if c.get('secure') else 'FALSE'
        exp = int(c.get('expires') or 0)
        lines.append(
            f'{c["domain"]}\t{sub}\t{c["path"]}\t{secure}\t{exp}\t{c["name"]}\t{c["value"]}'
        )
    return '\n'.join(lines) + '\n'


@app.get('/health')
async def health() -> dict:
    """Liveness probe."""
    return {'status': 'ok'}


def _get_cookies_b64(email: str, password: str, totp_secret: str) -> str:
    """Log into Google via headless Chromium; return base64-encoded cookies.txt."""
    import pyotp
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
        )
        page = ctx.new_page()

        page.goto(
            'https://accounts.google.com/signin/v2/identifier',
            wait_until='networkidle',
        )
        page.fill('input[type="email"]', email)
        page.click('#identifierNext')
        page.wait_for_load_state('networkidle')

        page.fill('input[type="password"]', password)
        page.click('#passwordNext')
        page.wait_for_load_state('networkidle')

        totp_el = page.query_selector('input[type="tel"], input[type="number"]')
        if totp_el:
            totp_el.fill(pyotp.TOTP(totp_secret).now())
            page.keyboard.press('Enter')
            page.wait_for_load_state('networkidle')

        google_cookies = [c for c in ctx.cookies() if 'google.com' in c['domain']]
        browser.close()

    logger.info('Auto-refresh: extracted %d google.com cookies', len(google_cookies))
    return base64.b64encode(_to_netscape(google_cookies).encode()).decode()


@app.post('/refresh')
async def refresh() -> dict:
    """Run headless Chrome login; return fresh base64 cookies."""
    email = os.environ.get('FAMILYLINK_GOOGLE_EMAIL', '')
    password = os.environ.get('FAMILYLINK_GOOGLE_PASSWORD', '')
    totp_secret = os.environ.get('FAMILYLINK_TOTP_SECRET', '')

    missing = [
        name
        for name, val in [
            ('FAMILYLINK_GOOGLE_EMAIL', email),
            ('FAMILYLINK_GOOGLE_PASSWORD', password),
            ('FAMILYLINK_TOTP_SECRET', totp_secret),
        ]
        if not val
    ]
    if missing:
        raise HTTPException(400, f'Missing env vars: {", ".join(missing)}')

    try:
        cookies_b64 = await asyncio.to_thread(
            _get_cookies_b64, email, password, totp_secret
        )
        return {'cookies_b64': cookies_b64}
    except Exception as exc:
        logger.error('Playwright login failed: %s', exc)
        raise HTTPException(500, str(exc))
