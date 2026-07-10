"""Sidecar: headless Chrome cookie refresher service."""

import logging

from fastapi import FastAPI

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
