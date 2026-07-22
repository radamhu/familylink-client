"""Sidecar: headless Chrome cookie refresher service."""

import asyncio
import base64
import logging
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title='cookie-refresher')

_refresh_lock = asyncio.Lock()


def _to_netscape(cookies: Sequence[Mapping[str, Any]]) -> str:
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


class StorageState(BaseModel):
    """Playwright browser-context storage_state payload."""

    cookies: list[dict]
    origins: list[dict] = []


@app.post('/bootstrap', status_code=204)
async def bootstrap(body: StorageState, x_api_key: str = Header(default='')) -> None:
    """Persist a storage_state JSON to disk for /refresh to reuse."""
    expected = os.environ.get('REFRESHER_API_KEY', '')
    if expected and x_api_key != expected:
        raise HTTPException(403, 'Forbidden')

    state_path = Path(os.environ.get('STATE_PATH', '/data/state.json'))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(body.model_dump_json())
    logger.info('Bootstrap: wrote %d cookies to %s', len(body.cookies), state_path)


def _get_cookies_b64(state_path: Path) -> str:
    """Replay a persisted Google session; return base64-encoded cookies.txt."""
    if not state_path.exists():
        raise RuntimeError(
            f'No persisted session at {state_path} — run bootstrap first'
        )

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=['--disable-blink-features=AutomationControlled']
        )
        ctx = browser.new_context(
            storage_state=str(state_path),
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            ),
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()

        try:
            page.goto('https://myaccount.google.com/', wait_until='networkidle')
        except Exception as exc:
            try:
                title = page.title()
            except Exception:
                title = '<unavailable>'
            browser.close()
            raise RuntimeError(
                f'Refresh navigation failed at {page.url!r} (title={title!r}): {exc}'
            ) from exc

        google_cookies = [c for c in ctx.cookies() if 'google.com' in c['domain']]
        if not any(c['name'] == 'SAPISID' for c in google_cookies):
            browser.close()
            raise RuntimeError(
                'Persisted session has no SAPISID after navigation — it has '
                'expired. Re-run scripts/bootstrap_refresher_session.py.'
            )

        ctx.storage_state(path=str(state_path))
        browser.close()

    cookies_b64 = base64.b64encode(_to_netscape(google_cookies).encode()).decode()
    _verify_family_link_access(cookies_b64)
    logger.info('Refresh: extracted %d google.com cookies', len(google_cookies))
    return cookies_b64


def _verify_family_link_access(cookies_b64: str) -> None:
    """Confirm the refreshed cookies actually authenticate against the Family Link API.

    myaccount.google.com accepts sessions that kidsmanagement-pa (Family Link's
    private API) already rejects, so presence of a SAPISID cookie alone is not
    sufficient evidence the refresh worked.
    """
    from familylink import FamilyLink

    prev_cookies_b64 = os.environ.get('FAMILYLINK_COOKIES_B64')
    prev_sapisid = os.environ.pop('FAMILYLINK_SAPISID', None)
    os.environ['FAMILYLINK_COOKIES_B64'] = cookies_b64
    try:
        FamilyLink().get_members()
    except Exception as exc:
        raise RuntimeError(
            f'Refreshed cookies failed Family Link API verification: {exc}'
        ) from exc
    finally:
        if prev_cookies_b64 is None:
            os.environ.pop('FAMILYLINK_COOKIES_B64', None)
        else:
            os.environ['FAMILYLINK_COOKIES_B64'] = prev_cookies_b64
        if prev_sapisid is not None:
            os.environ['FAMILYLINK_SAPISID'] = prev_sapisid


@app.post('/refresh')
async def refresh(x_api_key: str = Header(default='')) -> dict:
    """Replay the persisted Google session; return fresh base64 cookies.

    Serialized by `_refresh_lock`: _get_cookies_b64 reads and rewrites a
    single on-disk storage_state file, so two overlapping calls would race
    on that file instead of queueing safely.
    """
    expected = os.environ.get('REFRESHER_API_KEY', '')
    if expected and x_api_key != expected:
        raise HTTPException(403, 'Forbidden')

    state_path = Path(os.environ.get('STATE_PATH', '/data/state.json'))

    async with _refresh_lock:
        try:
            cookies_b64 = await asyncio.to_thread(_get_cookies_b64, state_path)
            return {'cookies_b64': cookies_b64}
        except Exception as exc:
            logger.error('Refresh failed: %s', exc)
            raise HTTPException(500, str(exc))
