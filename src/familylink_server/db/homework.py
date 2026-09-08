"""Shared homework_entries / ekreta_credentials DB helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from familylink_server.db.models import EkretaCredential, HomeworkEntry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def list_ekreta_credentials(session: AsyncSession) -> list[EkretaCredential]:
    """Return every configured kid's eKRÉTA login."""
    result = await session.execute(select(EkretaCredential))
    return list(result.scalars().all())


async def replace_homework_for_day(
    session: AsyncSession,
    child_id: str,
    day: date,
    entries: list[dict[str, str]],
) -> None:
    """Replace a kid's homework rows for `day` with `entries`.

    Each entry is `{'subject': str, 'description': str}`.
    """
    await session.execute(
        delete(HomeworkEntry).where(
            HomeworkEntry.child_id == child_id, HomeworkEntry.date == day
        )
    )
    fetched_at = datetime.now(UTC)
    for entry in entries:
        session.add(
            HomeworkEntry(
                child_id=child_id,
                date=day,
                subject=entry['subject'],
                description=entry['description'],
                fetched_at=fetched_at,
            )
        )


async def prune_homework_before(
    session: AsyncSession, child_id: str, cutoff: date
) -> None:
    """Delete a kid's homework rows older than `cutoff`."""
    await session.execute(
        delete(HomeworkEntry).where(
            HomeworkEntry.child_id == child_id, HomeworkEntry.date < cutoff
        )
    )


async def get_homework_for_day(
    session: AsyncSession, child_id: str, day: date
) -> list[HomeworkEntry]:
    """Return a kid's homework rows for `day`, ordered by subject."""
    result = await session.execute(
        select(HomeworkEntry)
        .where(HomeworkEntry.child_id == child_id, HomeworkEntry.date == day)
        .order_by(HomeworkEntry.subject)
    )
    return list(result.scalars().all())
