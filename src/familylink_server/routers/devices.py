"""Router for the /devices HTML page and HTMX lock/unlock endpoints."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=["devices"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


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
) -> HTMLResponse:
    """Lock a device and return the updated device card partial."""
    await svc.lock_device(device_id, child_id=child_id)
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
) -> HTMLResponse:
    """Unlock a device and return the updated device card partial."""
    await svc.unlock_device(device_id, child_id=child_id)
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
