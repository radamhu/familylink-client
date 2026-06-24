"""Router for the /devices HTML page and HTMX lock/unlock endpoints."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import AuditLog, get_session
from familylink_server.services.discord_notifier import get_notifier
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=["devices"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _child_name(svc: FamilyLinkService, child_id: str) -> str:
    members = await svc.get_members()
    return next(
        (m.profile.display_name for m in members.members if m.user_id == child_id),
        child_id,
    )


@router.get("/devices", response_class=HTMLResponse)
async def devices_page(
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Render the devices page listing all supervised devices."""
    members = await svc.get_members()
    children = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    devices = []
    for child in children:
        usage = await svc.get_apps_and_usage(child.user_id)
        for d in usage.device_info:
            devices.append(
                {
                    "device_id": d.device_id,
                    "child_id": child.user_id,
                    "friendly_name": d.display_info.friendly_name,
                    "model": getattr(d.display_info, "model", None),
                    "is_locked": False,
                }
            )
    return templates.TemplateResponse(request, "devices.html", {"devices": devices})


@router.post("/devices/{device_id}/lock", response_class=HTMLResponse)
async def lock_device(
    device_id: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Lock a device and return the updated device card partial."""
    await svc.lock_device(device_id, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        name = await _child_name(svc, child_id)
        await notifier.notify_change("lock_device", name, device_id, "web UI")
    session.add(
        AuditLog(
            child_id=child_id,
            action="lock_device",
            target=device_id,
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return templates.TemplateResponse(
        request,
        "partials/device_card.html",
        {
            "device": {
                "device_id": device_id,
                "child_id": child_id,
                "friendly_name": None,
                "is_locked": True,
            },
        },
    )


@router.post("/devices/{device_id}/unlock", response_class=HTMLResponse)
async def unlock_device(
    device_id: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Unlock a device and return the updated device card partial."""
    await svc.unlock_device(device_id, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        name = await _child_name(svc, child_id)
        await notifier.notify_change("unlock_device", name, device_id, "web UI")
    session.add(
        AuditLog(
            child_id=child_id,
            action="unlock_device",
            target=device_id,
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return templates.TemplateResponse(
        request,
        "partials/device_card.html",
        {
            "device": {
                "device_id": device_id,
                "child_id": child_id,
                "friendly_name": None,
                "is_locked": False,
            },
        },
    )
