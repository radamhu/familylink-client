"""Admin endpoints — protected, for operational management."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import get_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class RefreshCookiesRequest(BaseModel):
    """Request body for the refresh-cookies endpoint."""

    sapisid: str


@router.post("/refresh-cookies", status_code=204, dependencies=[require_user])
async def refresh_cookies(body: RefreshCookiesRequest) -> None:
    """Hot-swap the FamilyLink client with fresh cookies. No server restart needed."""
    get_service().reinit_with_cookies(body.sapisid)
    logger.info("Cookies hot-reloaded via /admin/refresh-cookies")
