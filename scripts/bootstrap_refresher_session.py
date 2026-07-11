"""One-time (or rare re-auth) bootstrap for the cookie-refresher sidecar.

Captures a real, already-authenticated Google session from the operator's
own browser via browser_cookie3 (same mechanism `familylink export-cookies`
uses) and uploads it to the deployed sidecar through the main app's
X-Api-Key-protected admin proxy. No automated login ever runs, so there is
nothing for Google's anti-automation detection to block.

Usage:
    WEB_BASE_URL=https://your-app.example.com \
    REFRESHER_API_KEY=<shared secret> \
    python scripts/bootstrap_refresher_session.py [--browser chrome]
"""

import argparse
import json
import os
import sys


def _cookiejar_to_storage_state(cookies: list) -> dict:
    """Convert browser_cookie3 cookie objects to a Playwright storage_state dict."""
    playwright_cookies = []
    for c in cookies:
        if 'google.com' not in c.domain:
            continue
        playwright_cookies.append(
            {
                'name': c.name,
                'value': c.value,
                'domain': c.domain,
                'path': c.path,
                'expires': c.expires if c.expires else -1,
                'httpOnly': 'HttpOnly' in getattr(c, '_rest', {}),
                'secure': bool(c.secure),
                'sameSite': 'None' if c.secure else 'Lax',
            }
        )
    return {'cookies': playwright_cookies, 'origins': []}


def main() -> int:
    """Extract cookies from browser and bootstrap the refresher sidecar."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--browser',
        default='chrome',
        help='browser_cookie3 function name to use (default: chrome)',
    )
    args = parser.parse_args()

    try:
        import browser_cookie3
    except ImportError:
        print(  # noqa: T201
            'browser_cookie3 not installed. Run: pip install -e ".[browser]"',
            file=sys.stderr,
        )
        return 1

    web_base_url = os.environ.get('WEB_BASE_URL', '').rstrip('/')
    api_key = os.environ.get('REFRESHER_API_KEY', '')
    if not web_base_url or not api_key:
        print('Set WEB_BASE_URL and REFRESHER_API_KEY env vars first.', file=sys.stderr)  # noqa: T201
        return 1

    jar = getattr(browser_cookie3, args.browser)(domain_name='google.com')
    storage_state = _cookiejar_to_storage_state(list(jar))

    if not any(c['name'] == 'SAPISID' for c in storage_state['cookies']):
        print(  # noqa: T201
            'No SAPISID cookie found — log into Google in that browser first.',
            file=sys.stderr,
        )
        return 1

    import httpx

    resp = httpx.post(
        f'{web_base_url}/admin/refresher-bootstrap',
        content=json.dumps(storage_state),
        headers={'Content-Type': 'application/json', 'X-Api-Key': api_key},
        timeout=30,
    )
    resp.raise_for_status()
    print(f'Bootstrapped {len(storage_state["cookies"])} cookies to the sidecar.')  # noqa: T201
    return 0


if __name__ == '__main__':
    sys.exit(main())
