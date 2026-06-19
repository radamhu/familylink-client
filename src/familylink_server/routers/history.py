"""Router for the /history audit log page."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import AuditLog, get_session

router = APIRouter(tags=["history"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
_PAGE_SIZE = 25


@router.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    page: int = 1,
    _email: str = require_user,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Render the audit log history page with infinite-scroll pagination."""
    offset = (page - 1) * _PAGE_SIZE
    q = (
        select(AuditLog)
        .order_by(desc(AuditLog.occurred_at))
        .offset(offset)
        .limit(_PAGE_SIZE)
    )
    logs = (await session.execute(q)).scalars().all()
    return templates.TemplateResponse(
        request,
        "history.html",
        {"logs": logs, "page": page, "has_more": len(logs) == _PAGE_SIZE},
    )
