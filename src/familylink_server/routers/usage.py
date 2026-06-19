"""Router for the /api/usage/today endpoint."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import UsageSnapshot, get_session

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/usage/today")
async def get_usage_today(
    _email: str = require_user,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict]:
    """Return the top-10 apps by usage seconds for today."""
    today = date.today()
    q = (
        select(
            UsageSnapshot.app_package,
            func.sum(UsageSnapshot.usage_seconds).label("total"),
        )
        .where(UsageSnapshot.date == today)
        .group_by(UsageSnapshot.app_package)
        .order_by(func.sum(UsageSnapshot.usage_seconds).desc())
        .limit(10)
    )
    rows = (await session.execute(q)).all()
    return [{"package": r.app_package, "seconds": r.total} for r in rows]
