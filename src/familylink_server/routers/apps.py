"""Router for the /apps HTML page and HTMX limit/block/allow endpoints."""

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

router = APIRouter(tags=["apps"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _child_name(svc: FamilyLinkService, child_id: str) -> str:
    members = await svc.get_members()
    return next(
        (m.profile.display_name for m in members.members if m.user_id == child_id),
        child_id,
    )


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
    child: str = "",
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Render the apps page with a per-child tab strip and inline edit controls."""
    members = await svc.get_members()
    supervised = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    children = [
        {"user_id": m.user_id, "display_name": m.profile.display_name}
        for m in supervised
    ]

    child_ids = {c["user_id"] for c in children}
    active_child_id = (
        child if child in child_ids else (children[0]["user_id"] if children else "")
    )

    apps = []
    if active_child_id:
        usage = await svc.get_apps_and_usage(active_child_id)
        apps = [
            dict(_app_state(a), child_id=active_child_id)
            for a in sorted(usage.apps, key=lambda x: x.title.lower())
        ]
        if filter != "all":
            apps = [a for a in apps if a["state"] == filter]

    return templates.TemplateResponse(
        request,
        "apps.html",
        {
            "apps": apps,
            "children": children,
            "active_child_id": active_child_id,
            "filter": filter,
        },
    )


@router.post("/apps/{package}/limit", response_class=HTMLResponse)
async def set_limit(
    package: str,
    request: Request,
    child_id: str = Form(...),
    minutes: int = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Set a daily usage limit for an app and return the updated row partial."""
    await svc.set_app_limit(package, minutes, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        name = await _child_name(svc, child_id)
        await notifier.notify_change(
            "set_limit", name, f"{package} ({minutes} min)", "web UI"
        )
    session.add(
        AuditLog(
            child_id=child_id,
            action="set_limit",
            target=package,
            new_value=str(minutes),
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    app_data = {
        "package_name": package,
        "title": package,
        "state": "limited",
        "state_label": f"Limited {minutes} min",
        "limit_mins": minutes,
        "child_id": child_id,
    }
    return templates.TemplateResponse(
        request, "partials/app_row.html", {"app": app_data}
    )


@router.post("/apps/{package}/block", response_class=HTMLResponse)
async def block_app(
    package: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Block an app and return the updated row partial."""
    await svc.block_app(package, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        name = await _child_name(svc, child_id)
        await notifier.notify_change("block", name, package, "web UI")
    session.add(
        AuditLog(
            child_id=child_id,
            action="block",
            target=package,
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    app_data = {
        "package_name": package,
        "title": package,
        "state": "blocked",
        "state_label": "Blocked",
        "limit_mins": None,
        "child_id": child_id,
    }
    return templates.TemplateResponse(
        request, "partials/app_row.html", {"app": app_data}
    )


@router.post("/apps/{package}/allow", response_class=HTMLResponse)
async def allow_app(
    package: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Always-allow an app and return the updated row partial."""
    await svc.always_allow_app(package, child_id=child_id)
    notifier = get_notifier()
    if notifier:
        name = await _child_name(svc, child_id)
        await notifier.notify_change("always_allow", name, package, "web UI")
    session.add(
        AuditLog(
            child_id=child_id,
            action="always_allow",
            target=package,
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    app_data = {
        "package_name": package,
        "title": package,
        "state": "allowed",
        "state_label": "Always allowed",
        "limit_mins": None,
        "child_id": child_id,
    }
    return templates.TemplateResponse(
        request, "partials/app_row.html", {"app": app_data}
    )
