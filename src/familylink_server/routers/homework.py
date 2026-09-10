"""Internal endpoints for the eKRÉTA scraper: credentials + homework ingest."""

import logging
import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.config import settings
from familylink_server.db import get_session
from familylink_server.db.homework import (
    list_ekreta_credentials,
    prune_expired_homework,
    upsert_homework_entries,
)
from familylink_server.services.ntfy_notifier import get_notifier

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix='/internal/ekreta', tags=['homework'], include_in_schema=False
)


def _require_ingest_token(x_api_key: str = Header(default='')) -> None:
    """Reject calls without the configured shared secret (fail closed)."""
    if not settings.ekreta_ingest_token or not secrets.compare_digest(
        x_api_key, settings.ekreta_ingest_token
    ):
        logger.warning('eKRÉTA ingest auth failed')
        raise HTTPException(401, 'Unauthorized')


class CredentialOut(BaseModel):
    """One kid's eKRÉTA login, as returned to the scraper."""

    child_id: str
    username: str
    password: str
    institution_code: str


class HomeworkEntryIn(BaseModel):
    """One scraped homework item, matching kreta_client.parse_homework_entry()."""

    subject: str
    teacher: str = ''
    deadline: date
    text: str = ''
    attachments: list[str] = []


class HomeworkIngestIn(BaseModel):
    """Body of POST /internal/ekreta/homework."""

    child_id: str
    entries: list[HomeworkEntryIn]


def _format_description(entry: HomeworkEntryIn) -> str:
    """Render a scraped entry's teacher/text/attachments as display text.

    The deadline is not included here — it's a first-class column, shown
    separately by the dashboard.
    """
    lines = []
    if entry.teacher:
        lines.append(f'Teacher: {entry.teacher}')
    if entry.text:
        lines.append(entry.text)
    if entry.attachments:
        lines.append('Attachments: ' + ', '.join(entry.attachments))
    return '\n'.join(lines)


@router.get('/credentials', response_model=list[CredentialOut])
async def get_credentials(
    _auth: None = Depends(_require_ingest_token),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[CredentialOut]:
    """Return every configured kid's eKRÉTA login for the scraper to use."""
    rows = await list_ekreta_credentials(session)
    return [
        CredentialOut(
            child_id=row.child_id,
            username=row.username,
            password=row.password,
            institution_code=row.institution_code,
        )
        for row in rows
    ]


@router.post('/homework', status_code=204)
async def ingest_homework(
    body: HomeworkIngestIn,
    _auth: None = Depends(_require_ingest_token),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Upsert a kid's homework by identity, then prune expired rows."""
    today = date.today()
    entries = [
        {
            'subject': e.subject,
            'deadline': e.deadline,
            'description': _format_description(e),
        }
        for e in body.entries
    ]
    new_entries = await upsert_homework_entries(session, body.child_id, today, entries)
    await prune_expired_homework(session, body.child_id, today)
    await session.commit()

    ntfy = get_notifier()
    if ntfy and new_entries:
        if len(new_entries) == 1:
            entry = new_entries[0]
            await ntfy.notify_homework(
                body.child_id, entry['subject'], entry['deadline'].isoformat()
            )
        else:
            summary = ', '.join(
                f'{e["subject"]} ({e["deadline"].isoformat()})' for e in new_entries
            )
            await ntfy.send(
                body.child_id,
                title=f'📚 {len(new_entries)} new assignments',
                message=summary,
                tags=['book'],
            )
