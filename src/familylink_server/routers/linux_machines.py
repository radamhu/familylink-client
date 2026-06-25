"""Router for /linux-machines CRUD and HTMX action endpoints."""

import logging
from datetime import UTC, date, datetime
from pathlib import Path

import asyncssh
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import AuditLog, get_session
from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot
from familylink_server.services.family_link import FamilyLinkService, get_service
from familylink_server.services.linux_ssh import lock_session, poweroff_machine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["linux_machines"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _get_machine_or_404(machine_id: int, session: AsyncSession) -> LinuxMachine:
    machine = await session.get(LinuxMachine, machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


async def _today_snapshot(
    machine_id: int, session: AsyncSession
) -> LinuxUsageSnapshot | None:
    result = await session.execute(
        select(LinuxUsageSnapshot).where(
            LinuxUsageSnapshot.machine_id == machine_id,
            LinuxUsageSnapshot.date == date.today(),
        )
    )
    return result.scalar_one_or_none()


def _machine_context(
    machine: LinuxMachine, snapshot: LinuxUsageSnapshot | None
) -> dict:
    active_mins = (snapshot.active_seconds // 60) if snapshot else 0
    if snapshot and snapshot.poweroff_at:
        status = "powered_off"
    elif snapshot and snapshot.locked_at:
        status = "locked"
    else:
        status = "active"
    return {"machine": machine, "active_mins": active_mins, "status": status}


async def _child_names(svc: FamilyLinkService) -> dict[str, str]:
    members = await svc.get_members()
    return {m.user_id: m.profile.display_name for m in members.members}


@router.get("/linux-machines", response_class=HTMLResponse)
async def linux_machines_page(
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Render the Linux Machines page."""
    result = await session.execute(
        select(LinuxMachine).order_by(LinuxMachine.friendly_name)
    )
    machines = result.scalars().all()
    children = await _child_names(svc)
    rows = []
    for m in machines:
        snapshot = await _today_snapshot(m.id, session)
        ctx = _machine_context(m, snapshot)
        ctx["child_name"] = children.get(m.child_id, m.child_id)
        rows.append(ctx)
    return templates.TemplateResponse(
        request,
        "linux_machines.html",
        {"machines": rows, "children": children},
    )


@router.get("/linux-machines/new", response_class=HTMLResponse)
async def new_machine_form(
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Render the add-machine form."""
    children = await _child_names(svc)
    return templates.TemplateResponse(
        request,
        "linux_machine_form.html",
        {"machine": None, "children": children},
    )


@router.post("/linux-machines")
async def create_machine(
    friendly_name: str = Form(...),
    child_id: str = Form(...),
    hostname: str = Form(...),
    ssh_port: int = Form(22),
    ssh_user: str = Form(...),
    ssh_private_key: str = Form(...),
    daily_limit_mins: int | None = Form(None),
    grace_period_mins: int = Form(5),
    enabled: bool = Form(False),
    _email: str = require_user,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RedirectResponse:
    """Create a new Linux machine record."""
    session.add(
        LinuxMachine(
            friendly_name=friendly_name,
            child_id=child_id,
            hostname=hostname,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_private_key=ssh_private_key,
            daily_limit_mins=daily_limit_mins,
            grace_period_mins=grace_period_mins,
            enabled=enabled,
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return RedirectResponse("/linux-machines", status_code=303)


@router.post("/linux-machines/generate-key")
async def generate_key_pair(
    _email: str = require_user,  # type: ignore[assignment]
) -> JSONResponse:
    """Generate an ed25519 SSH key pair and return both halves as strings."""
    key = asyncssh.generate_private_key("ssh-ed25519")
    private_pem = key.export_private_key("openssh").decode()
    public_openssh = key.export_public_key("openssh").decode().strip()
    return JSONResponse({"private_key": private_pem, "public_key": public_openssh})


@router.get("/linux-machines/{machine_id}/edit", response_class=HTMLResponse)
async def edit_machine_form(
    machine_id: int,
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Render the edit-machine form."""
    machine = await _get_machine_or_404(machine_id, session)
    children = await _child_names(svc)
    return templates.TemplateResponse(
        request,
        "linux_machine_form.html",
        {"machine": machine, "children": children},
    )


@router.post("/linux-machines/{machine_id}/edit")
async def update_machine(
    machine_id: int,
    friendly_name: str = Form(...),
    child_id: str = Form(...),
    hostname: str = Form(...),
    ssh_port: int = Form(22),
    ssh_user: str = Form(...),
    ssh_private_key: str = Form(""),
    daily_limit_mins: int | None = Form(None),
    grace_period_mins: int = Form(5),
    enabled: bool = Form(False),
    _email: str = require_user,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RedirectResponse:
    """Update an existing Linux machine record."""
    machine = await _get_machine_or_404(machine_id, session)
    machine.friendly_name = friendly_name
    machine.child_id = child_id
    machine.hostname = hostname
    machine.ssh_port = ssh_port
    machine.ssh_user = ssh_user
    if ssh_private_key.strip():
        machine.ssh_private_key = ssh_private_key
    machine.daily_limit_mins = daily_limit_mins
    machine.grace_period_mins = grace_period_mins
    machine.enabled = enabled
    await session.commit()
    return RedirectResponse("/linux-machines", status_code=303)


@router.delete("/linux-machines/{machine_id}", response_class=HTMLResponse)
async def delete_machine(
    machine_id: int,
    _email: str = require_user,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Delete a Linux machine and return empty string for HTMX outerHTML swap."""
    machine = await _get_machine_or_404(machine_id, session)
    await session.delete(machine)
    await session.commit()
    return HTMLResponse("")


@router.post("/linux-machines/{machine_id}/lock", response_class=HTMLResponse)
async def lock_machine(
    machine_id: int,
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Lock the machine immediately and return the updated card partial."""
    machine = await _get_machine_or_404(machine_id, session)
    try:
        await lock_session(
            machine.hostname,
            machine.ssh_port,
            machine.ssh_user,
            machine.ssh_private_key,
        )
    except Exception:
        logger.warning("lock_session failed for %s", machine.friendly_name)
        return HTMLResponse(
            "<p>SSH connection failed. Is the machine online?</p>", status_code=502
        )
    snapshot = await _today_snapshot(machine_id, session)
    now = datetime.now(UTC)
    if snapshot is None:
        snapshot = LinuxUsageSnapshot(
            machine_id=machine_id,
            date=date.today(),
            active_seconds=0,
            updated_at=now,
        )
        session.add(snapshot)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            snapshot = (
                await session.execute(
                    select(LinuxUsageSnapshot).where(
                        LinuxUsageSnapshot.machine_id == machine_id,
                        LinuxUsageSnapshot.date == date.today(),
                    )
                )
            ).scalar_one()
            now = datetime.now(UTC)
    if snapshot.locked_at is None:
        snapshot.locked_at = now
        snapshot.updated_at = now
    session.add(
        AuditLog(
            child_id=machine.child_id,
            action="lock_linux",
            target=machine.friendly_name,
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    children = await _child_names(svc)
    ctx = _machine_context(machine, snapshot)
    ctx["child_name"] = children.get(machine.child_id, machine.child_id)
    return templates.TemplateResponse(request, "partials/linux_machine_card.html", ctx)


@router.post("/linux-machines/{machine_id}/poweroff", response_class=HTMLResponse)
async def poweroff_machine_endpoint(
    machine_id: int,
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Power off the machine immediately and return the updated card partial."""
    machine = await _get_machine_or_404(machine_id, session)
    try:
        await poweroff_machine(
            machine.hostname,
            machine.ssh_port,
            machine.ssh_user,
            machine.ssh_private_key,
        )
    except Exception:
        logger.warning("poweroff_machine failed for %s", machine.friendly_name)
        return HTMLResponse(
            "<p>SSH connection failed. Is the machine online?</p>", status_code=502
        )
    snapshot = await _today_snapshot(machine_id, session)
    now = datetime.now(UTC)
    if snapshot is None:
        snapshot = LinuxUsageSnapshot(
            machine_id=machine_id,
            date=date.today(),
            active_seconds=0,
            updated_at=now,
        )
        session.add(snapshot)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            snapshot = (
                await session.execute(
                    select(LinuxUsageSnapshot).where(
                        LinuxUsageSnapshot.machine_id == machine_id,
                        LinuxUsageSnapshot.date == date.today(),
                    )
                )
            ).scalar_one()
            now = datetime.now(UTC)
    if snapshot.locked_at is None:
        snapshot.locked_at = now
    snapshot.poweroff_at = now
    snapshot.updated_at = now
    session.add(
        AuditLog(
            child_id=machine.child_id,
            action="poweroff_linux",
            target=machine.friendly_name,
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    children = await _child_names(svc)
    ctx = _machine_context(machine, snapshot)
    ctx["child_name"] = children.get(machine.child_id, machine.child_id)
    return templates.TemplateResponse(request, "partials/linux_machine_card.html", ctx)
