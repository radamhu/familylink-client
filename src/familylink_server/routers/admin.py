"""Admin endpoints — protected, for operational management."""

import logging
import secrets

import httpx
from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from familylink_server.config import settings
from familylink_server.services.family_link import FamilyLinkService, get_service

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


@router.post('/sapisid-relay', response_class=HTMLResponse)
async def sapisid_relay(
    sapisid: str = Form(...),
    # Default '' (not required): FastAPI's Form(...) treats an empty-string
    # submission on a *required* field as missing (422) rather than ''. We
    # need '' to actually reach the compare_digest check below so an unset
    # token is rejected as 403 (Forbidden), not 422.
    token: str = Form(''),
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Hot-swap the FamilyLink client from a SAPISID posted by the Android bookmarklet.

    No `require_user` — this is invoked cross-origin (a plain form POST from a
    javascript: bookmarklet on a google.com tab) with no `fl_session` cookie
    available. The `token` field is this endpoint's only access control.
    """
    expected = settings.sapisid_relay_token
    if not expected or not secrets.compare_digest(token, expected):
        return HTMLResponse('<p>Forbidden.</p>', status_code=403)

    svc.reinit_with_sapisid(sapisid)
    try:
        await svc.get_members()
    except Exception as exc:
        logger.error('SAPISID relay: verification failed — %s', exc)
        return HTMLResponse(f'<p>Reconnect failed: {exc}</p>', status_code=502)

    svc.set_auth_failed(False)
    logger.info('SAPISID relay: reconnected via bookmarklet')
    return HTMLResponse('<p>Reconnected.</p>')
