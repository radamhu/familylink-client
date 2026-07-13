"""Router for the /apps HTML page and HTMX limit/block/allow endpoints."""

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.constants import CHILD_COLORS
from familylink_server.db import (
    AppConfig,
    AuditLog,
    get_or_create_app_config,
    get_session,
)
from familylink_server.services.discord_notifier import get_notifier
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=['apps'])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / 'templates'))

VALID_BONUS_MINUTES = {15, 30, 60}


async def _child_name(svc: FamilyLinkService, child_id: str) -> str:
    members = await svc.get_members()
    return next(
        (m.profile.display_name for m in members.members if m.user_id == child_id),
        child_id,
    )


def _app_state(app) -> dict:
    sup = app.supervision_setting
    if sup.hidden:
        state, state_label = 'blocked', 'Blocked'
    elif sup.usage_limit:
        state, state_label = (
            'limited',
            f'Limited {sup.usage_limit.daily_usage_limit_mins} min',
        )
    elif sup.always_allowed_app_info:
        state, state_label = 'allowed', 'Always allowed'
    else:
        state, state_label = 'unmanaged', 'Unmanaged'
    return {
        'package_name': app.package_name,
        'title': app.title,
        'state': state,
        'state_label': state_label,
        'limit_mins': sup.usage_limit.daily_usage_limit_mins
        if sup.usage_limit
        else None,
    }


@router.get('/apps', response_class=HTMLResponse)
async def apps_page(
    request: Request,
    filter: str = 'all',
    child: str = '',
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Render the apps page with a per-child tab strip and inline edit controls."""
    members = await svc.get_members()
    supervised = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    children = [
        {
            'user_id': m.user_id,
            'display_name': m.profile.display_name,
            'color': CHILD_COLORS[i % len(CHILD_COLORS)],
        }
        for i, m in enumerate(supervised)
    ]

    child_ids = {c['user_id'] for c in children}
    active_child_id = (
        child if child in child_ids else (children[0]['user_id'] if children else '')
    )

    apps = []
    if active_child_id:
        usage = await svc.get_apps_and_usage(active_child_id)
        result = await session.execute(
            select(AppConfig).where(AppConfig.child_id == active_child_id)
        )
        configs_by_package = {c.package_name: c for c in result.scalars().all()}
        for a in sorted(usage.apps, key=lambda x: x.title.lower()):
            config = configs_by_package.get(a.package_name)
            apps.append(
                dict(
                    _app_state(a),
                    child_id=active_child_id,
                    auto_block_enabled=config.auto_block_enabled if config else False,
                    auto_blocked_at=config.auto_blocked_at if config else None,
                )
            )
        if filter != 'all':
            apps = [a for a in apps if a['state'] == filter]

    return templates.TemplateResponse(
        request,
        'apps.html',
        {
            'apps': apps,
            'children': children,
            'active_child_id': active_child_id,
            'filter': filter,
            'auth_failed': svc.auth_failed,
        },
    )


@router.post('/apps/{package}/limit', response_class=HTMLResponse)
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
            'set_limit', name, f'{package} ({minutes} min)', 'web UI'
        )
    session.add(
        AuditLog(
            child_id=child_id,
            action='set_limit',
            target=package,
            new_value=str(minutes),
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    config_result = await session.execute(
        select(AppConfig).where(
            AppConfig.child_id == child_id, AppConfig.package_name == package
        )
    )
    config = config_result.scalar_one_or_none()
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'limited',
        'state_label': f'Limited {minutes} min',
        'limit_mins': minutes,
        'child_id': child_id,
        'auto_block_enabled': config.auto_block_enabled if config else False,
        'auto_blocked_at': config.auto_blocked_at if config else None,
    }
    return templates.TemplateResponse(
        request, 'partials/app_row.html', {'app': app_data}
    )


@router.post('/apps/{package}/block', response_class=HTMLResponse)
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
        await notifier.notify_change('block', name, package, 'web UI')
    session.add(
        AuditLog(
            child_id=child_id,
            action='block',
            target=package,
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'blocked',
        'state_label': 'Blocked',
        'limit_mins': None,
        'child_id': child_id,
    }
    return templates.TemplateResponse(
        request, 'partials/app_row.html', {'app': app_data}
    )


@router.post('/apps/{package}/allow', response_class=HTMLResponse)
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
        await notifier.notify_change('always_allow', name, package, 'web UI')
    session.add(
        AuditLog(
            child_id=child_id,
            action='always_allow',
            target=package,
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'allowed',
        'state_label': 'Always allowed',
        'limit_mins': None,
        'child_id': child_id,
    }
    return templates.TemplateResponse(
        request, 'partials/app_row.html', {'app': app_data}
    )


@router.post('/apps/{package}/auto-block', response_class=HTMLResponse)
async def set_auto_block(
    package: str,
    request: Request,
    child_id: str = Form(...),
    limit_mins: int = Form(...),
    enabled: bool = Form(False),
    _email: str = require_user,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Toggle auto-block-on-overuse opt-in for an app and return the updated row partial."""
    config = await get_or_create_app_config(session, child_id, package)
    config.auto_block_enabled = enabled
    session.add(
        AuditLog(
            child_id=child_id,
            action='auto_block_toggle',
            target=package,
            new_value=str(enabled),
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'limited',
        'state_label': f'Limited {limit_mins} min',
        'limit_mins': limit_mins,
        'child_id': child_id,
        'auto_block_enabled': config.auto_block_enabled,
        'auto_blocked_at': None,
    }
    return templates.TemplateResponse(
        request, 'partials/app_row.html', {'app': app_data}
    )


@router.post('/apps/{package}/bonus', response_class=HTMLResponse)
async def grant_bonus(
    package: str,
    request: Request,
    child_id: str = Form(...),
    minutes: int = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Grant bonus minutes to an auto-blocked app, unblocking it immediately."""
    if minutes not in VALID_BONUS_MINUTES:
        raise HTTPException(
            status_code=400, detail='minutes must be one of 15, 30, or 60'
        )
    config = await get_or_create_app_config(session, child_id, package)
    today = date.today()
    if config.bonus_date != today:
        config.bonus_mins = minutes
        config.bonus_date = today
    else:
        config.bonus_mins += minutes

    if config.auto_blocked_at is not None:
        usage = await svc.get_apps_and_usage(child_id)
        app_match = next((a for a in usage.apps if a.package_name == package), None)
        base_limit = (
            app_match.supervision_setting.usage_limit.daily_usage_limit_mins
            if app_match is not None and app_match.supervision_setting.usage_limit
            else 0
        )
        await svc.set_app_limit(package, base_limit, child_id)
        config.auto_blocked_at = None
        state, state_label, limit_mins = (
            'limited',
            f'Limited {base_limit} min (+{config.bonus_mins} bonus today)',
            base_limit,
        )
    else:
        state, state_label, limit_mins = 'blocked', 'Blocked', None

    session.add(
        AuditLog(
            child_id=child_id,
            action='bonus_app',
            target=package,
            new_value=str(minutes),
            occurred_at=datetime.now(UTC),
        )
    )
    await session.commit()

    app_data = {
        'package_name': package,
        'title': package,
        'state': state,
        'state_label': state_label,
        'limit_mins': limit_mins,
        'child_id': child_id,
        'auto_block_enabled': config.auto_block_enabled,
        'auto_blocked_at': config.auto_blocked_at,
    }
    return templates.TemplateResponse(
        request, 'partials/app_row.html', {'app': app_data}
    )
