"""Router for the main dashboard page."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Render the dashboard with per-child usage summaries."""
    members = await svc.get_members()
    children = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    child_data = []
    for child in children:
        usage = await svc.get_apps_and_usage(child.user_id)
        total_seconds = sum(int(float(s.usage)) for s in usage.app_usage_sessions)
        top_apps: dict[str, int] = {}
        for s in usage.app_usage_sessions:
            pkg = s.app_id.android_app_package_name
            top_apps[pkg] = top_apps.get(pkg, 0) + int(float(s.usage))
        top5 = sorted(top_apps.items(), key=lambda x: x[1], reverse=True)[:5]
        # Build lookup dict — AppUsage has no get_app_title() method
        title_by_pkg = {a.package_name: a.title for a in usage.apps}
        top5_named = [
            {"title": title_by_pkg.get(pkg, pkg), "seconds": secs} for pkg, secs in top5
        ]
        devices = [
            {
                "device_id": d.device_id,
                "friendly_name": d.display_info.friendly_name,
                "is_locked": False,
            }
            for d in usage.device_info
        ]
        child_data.append(
            {
                "display_name": child.profile.display_name,
                "user_id": child.user_id,
                "total_seconds": total_seconds,
                "top5": top5_named,
                "devices": devices,
            }
        )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"children": child_data},
    )
