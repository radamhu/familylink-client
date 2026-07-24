"""Sidecar: reads cookies from a persistent, logged-in Firefox profile."""

import asyncio
import base64
import logging
import os
from collections.abc import Iterable
from pathlib import Path

import browser_cookie3
from fastapi import FastAPI, Header, HTTPException

logger = logging.getLogger(__name__)

app = FastAPI(title='cookie-refresher')

_refresh_lock = asyncio.Lock()


class NotLoggedInError(Exception):
    """Raised when the Firefox profile has no usable Google session."""


@app.get('/health')
async def health() -> dict:
    """Liveness probe."""
    return {'status': 'ok'}


def _profile_cookie_file() -> Path | None:
    """Return the first cookies.sqlite under FIREFOX_PROFILE_DIR, or None."""
    root = Path(os.environ.get('FIREFOX_PROFILE_DIR', '/profile'))
    if not root.exists():
        return None
    return next(iter(sorted(root.rglob('cookies.sqlite'))), None)


def _read_live_google_cookies(sqlite_path: Path) -> list:
    """Read google.com cookies from the live Firefox profile.

    Raises:
        NotLoggedInError: if the profile holds no SAPISID cookie.
    """
    jar = browser_cookie3.firefox(
        cookie_file=str(sqlite_path), domain_name='google.com'
    )
    cookies = [c for c in jar if 'google.com' in c.domain]
    if not any(c.name == 'SAPISID' for c in cookies):
        raise NotLoggedInError('Firefox profile has no SAPISID — sign in via noVNC.')
    return cookies


def _jar_to_netscape(cookies: Iterable) -> str:
    """Convert browser_cookie3 cookie objects to Netscape cookies.txt format."""
    lines = ['# Netscape HTTP Cookie File']
    for c in cookies:
        sub = 'TRUE' if c.domain.startswith('.') else 'FALSE'
        secure = 'TRUE' if c.secure else 'FALSE'
        exp = int(c.expires or 0)
        lines.append(
            f'{c.domain}\t{sub}\t{c.path}\t{secure}\t{exp}\t{c.name}\t{c.value}'
        )
    return '\n'.join(lines) + '\n'


def _verify_family_link_access(cookies_b64: str) -> None:
    """Confirm the cookies authenticate against the Family Link API.

    myaccount.google.com accepts sessions that kidsmanagement-pa rejects, so a
    real API call is the only trustworthy liveness check.
    """
    from familylink import FamilyLink

    prev_b64 = os.environ.get('FAMILYLINK_COOKIES_B64')
    prev_sapisid = os.environ.pop('FAMILYLINK_SAPISID', None)
    os.environ['FAMILYLINK_COOKIES_B64'] = cookies_b64
    try:
        FamilyLink().get_members()
    except Exception as exc:
        raise RuntimeError(
            f'Refreshed cookies failed Family Link API verification: {exc}'
        ) from exc
    finally:
        if prev_b64 is None:
            os.environ.pop('FAMILYLINK_COOKIES_B64', None)
        else:
            os.environ['FAMILYLINK_COOKIES_B64'] = prev_b64
        if prev_sapisid is not None:
            os.environ['FAMILYLINK_SAPISID'] = prev_sapisid


def _build_verified_cookies_b64(sqlite_path: Path) -> str:
    """Read live cookies, verify against the Family Link API, return base64.

    Raises:
        NotLoggedInError: if the profile holds no SAPISID cookie.
        RuntimeError: if the cookies fail Family Link API verification.
    """
    cookies = _read_live_google_cookies(sqlite_path)
    cookies_b64 = base64.b64encode(_jar_to_netscape(cookies).encode()).decode()
    _verify_family_link_access(cookies_b64)
    logger.info('Refresh: returned %d live google.com cookies', len(cookies))
    return cookies_b64


@app.post('/refresh')
async def refresh(x_api_key: str = Header(default='')) -> dict:
    """Read live cookies from the Firefox profile; verify; return base64."""
    expected = os.environ.get('REFRESHER_API_KEY', '')
    if expected and x_api_key != expected:
        raise HTTPException(403, 'Forbidden')

    sqlite_path = _profile_cookie_file()
    if sqlite_path is None:
        raise HTTPException(409, 'Firefox profile not initialised — sign in via noVNC.')

    try:
        async with _refresh_lock:
            cookies_b64 = await asyncio.to_thread(
                _build_verified_cookies_b64, sqlite_path
            )
    except NotLoggedInError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        logger.error('Refresh failed: %s', exc)
        raise HTTPException(502, str(exc)) from exc

    return {'cookies_b64': cookies_b64}
