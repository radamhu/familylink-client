"""Router for the main dashboard page."""

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import get_session
from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Render the dashboard with per-child usage summaries."""
    today = date.today()
    members = await svc.get_members()
    children = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    child_data = []
    for child in children:
        usage = await svc.get_apps_and_usage(child.user_id)
        today_sessions = [
            s
            for s in usage.app_usage_sessions
            if s.date.year == today.year
            and s.date.month == today.month
            and s.date.day == today.day
        ]
        total_seconds = sum(int(float(s.usage)) for s in today_sessions)
        top_apps: dict[str, int] = {}
        for s in today_sessions:
            pkg = s.app_id.android_app_package_name
            top_apps[pkg] = top_apps.get(pkg, 0) + int(float(s.usage))
        top5 = sorted(top_apps.items(), key=lambda x: x[1], reverse=True)[:5]
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

        machine_result = await session.execute(
            select(LinuxMachine).where(
                LinuxMachine.child_id == child.user_id,
                LinuxMachine.enabled.is_(True),
            )
        )
        machines = machine_result.scalars().all()
        linux_rows = []
        for m in machines:
            snap_result = await session.execute(
                select(LinuxUsageSnapshot).where(
                    LinuxUsageSnapshot.machine_id == m.id,
                    LinuxUsageSnapshot.date == today,
                )
            )
            snap = snap_result.scalar_one_or_none()
            active_mins = (snap.active_seconds // 60) if snap else 0
            bonus_mins = snap.bonus_mins if snap else 0
            effective_limit_mins = (
                m.daily_limit_mins + bonus_mins
                if m.daily_limit_mins is not None
                else None
            )
            if snap and snap.poweroff_at:
                lm_status = "powered_off"
            elif snap and snap.locked_at:
                lm_status = "locked"
            else:
                lm_status = "active"
            linux_rows.append(
                {
                    "friendly_name": m.friendly_name,
                    "active_mins": active_mins,
                    "effective_limit_mins": effective_limit_mins,
                    "status": lm_status,
                }
            )

        child_data.append(
            {
                "display_name": child.profile.display_name,
                "user_id": child.user_id,
                "total_seconds": total_seconds,
                "top5": top5_named,
                "devices": devices,
                "linux_machines": linux_rows,
            }
        )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"children": child_data},
    )
