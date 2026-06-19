"""Router for the /apps HTML page and HTMX limit/block/allow endpoints."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=["apps"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _app_state(app) -> dict:
    sup = app.supervision_setting
    if sup.hidden:
        state, state_label = "blocked", "Blocked"
    elif sup.usage_limit:
        state, state_label = (
            "limited",
            f"Limited {sup.usage_limit.daily_usage_limit_mins} min",
        )
    elif sup.always_allowed_app_info:
        state, state_label = "allowed", "Always allowed"
    else:
        state, state_label = "unmanaged", "Unmanaged"
    return {
        "package_name": app.package_name,
        "title": app.title,
        "state": state,
        "state_label": state_label,
        "limit_mins": sup.usage_limit.daily_usage_limit_mins
        if sup.usage_limit
        else None,
    }


@router.get("/apps", response_class=HTMLResponse)
async def apps_page(
    request: Request,
    filter: str = "all",
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Render the apps page listing all supervised apps with inline edit controls."""
    members = await svc.get_members()
    children = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    child = children[0] if children else None
    apps = []
    if child:
        usage = await svc.get_apps_and_usage(child.user_id)
        apps = [
            dict(_app_state(a), child_id=child.user_id)
            for a in sorted(usage.apps, key=lambda x: x.title.lower())
        ]
        if filter != "all":
            apps = [a for a in apps if a["state"] == filter]
    return templates.TemplateResponse(
        request,
        "apps.html",
        {"apps": apps, "child_id": child.user_id if child else "", "filter": filter},
    )


@router.post("/apps/{package}/limit", response_class=HTMLResponse)
async def set_limit(
    package: str,
    request: Request,
    child_id: str = Form(...),
    minutes: int = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Set a daily usage limit for an app and return the updated row partial."""
    await svc.set_app_limit(package, minutes, child_id=child_id)
    app_data = {
        "package_name": package,
        "title": package,
        "state": "limited",
        "state_label": f"Limited {minutes} min",
        "limit_mins": minutes,
        "child_id": child_id,
    }
    return templates.TemplateResponse(
        request,
        "partials/app_row.html",
        {"app": app_data},
    )


@router.post("/apps/{package}/block", response_class=HTMLResponse)
async def block_app(
    package: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Block an app and return the updated row partial."""
    await svc.block_app(package, child_id=child_id)
    app_data = {
        "package_name": package,
        "title": package,
        "state": "blocked",
        "state_label": "Blocked",
        "limit_mins": None,
        "child_id": child_id,
    }
    return templates.TemplateResponse(
        request,
        "partials/app_row.html",
        {"app": app_data},
    )


@router.post("/apps/{package}/allow", response_class=HTMLResponse)
async def allow_app(
    package: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Always-allow an app and return the updated row partial."""
    await svc.always_allow_app(package, child_id=child_id)
    app_data = {
        "package_name": package,
        "title": package,
        "state": "allowed",
        "state_label": "Always allowed",
        "limit_mins": None,
        "child_id": child_id,
    }
    return templates.TemplateResponse(
        request,
        "partials/app_row.html",
        {"app": app_data},
    )
