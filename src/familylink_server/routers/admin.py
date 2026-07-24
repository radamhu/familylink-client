"""Admin endpoints — protected, for operational management."""

import logging

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from familylink_server.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/admin', tags=['admin'])


@router.post('/refresher-bootstrap', status_code=204)
async def refresher_bootstrap(
    request: Request, x_api_key: str = Header(default='')
) -> None:
    """Proxy a bootstrapped Playwright storage_state to the cookie-refresher sidecar."""
    expected = settings.refresher_api_key
    if expected and x_api_key != expected:
        raise HTTPException(403, 'Forbidden')
    if not settings.cookie_refresher_url:
        raise HTTPException(400, 'COOKIE_REFRESHER_URL is not configured')

    body = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f'{settings.cookie_refresher_url}/bootstrap',
                content=body,
                headers={
                    'Content-Type': 'application/json',
                    'X-Api-Key': settings.refresher_api_key,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                502,
                f'Sidecar rejected bootstrap: {exc.response.status_code} {exc.response.text}',
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f'Sidecar unreachable: {exc}') from exc
    logger.info('Bootstrap proxied to cookie-refresher sidecar')
