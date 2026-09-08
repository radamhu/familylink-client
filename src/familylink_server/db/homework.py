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


async def upsert_homework_entries(
    session: AsyncSession,
    child_id: str,
    today: date,
    entries: list[dict[str, str | date]],
) -> None:
    """Insert-or-refresh a kid's homework, keyed by (child_id, subject, deadline).

    Each entry is `{'subject': str, 'deadline': date, 'description': str}`. A
    still-open item scraped again refreshes its description/date/fetched_at
    in place rather than duplicating.
    """
    fetched_at = datetime.now(UTC)
    for entry in entries:
        existing = (
            await session.execute(
                select(HomeworkEntry).where(
                    HomeworkEntry.child_id == child_id,
                    HomeworkEntry.subject == entry['subject'],
                    HomeworkEntry.deadline == entry['deadline'],
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.description = entry['description']
            existing.date = today
            existing.fetched_at = fetched_at
        else:
            session.add(
                HomeworkEntry(
                    child_id=child_id,
                    date=today,
                    subject=entry['subject'],
                    deadline=entry['deadline'],
                    description=entry['description'],
                    fetched_at=fetched_at,
                )
            )


async def prune_expired_homework(
    session: AsyncSession, child_id: str, today: date
) -> None:
    """Delete a kid's homework rows whose deadline has already passed."""
    await session.execute(
        delete(HomeworkEntry).where(
            HomeworkEntry.child_id == child_id, HomeworkEntry.deadline < today
        )
    )


async def get_upcoming_homework(
    session: AsyncSession, child_id: str, today: date
) -> list[HomeworkEntry]:
    """Return a kid's not-yet-due homework, ordered by deadline then subject."""
    result = await session.execute(
        select(HomeworkEntry)
        .where(HomeworkEntry.child_id == child_id, HomeworkEntry.deadline >= today)
        .order_by(HomeworkEntry.deadline, HomeworkEntry.subject)
    )
    return list(result.scalars().all())
