"""Tests for homework_entries/ekreta_credentials DB helpers (real in-memory DB)."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from familylink_server.db.homework import (
    get_homework_for_day,
    list_ekreta_credentials,
    prune_homework_before,
    replace_homework_for_day,
)
from familylink_server.db.models import Base, EkretaCredential, HomeworkEntry


@pytest.fixture
async def db_session():
    """Provide an in-memory SQLite session for testing."""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_ekreta_credentials_returns_all_rows(db_session):
    db_session.add(
        EkretaCredential(
            child_id='child1', username='u', password='p', institution_code='035120'
        )
    )
    await db_session.commit()
    rows = await list_ekreta_credentials(db_session)
    assert [r.child_id for r in rows] == ['child1']


@pytest.mark.asyncio
async def test_replace_homework_for_day_replaces_prior_entries(db_session):
    await replace_homework_for_day(
        db_session,
        'child1',
        date(2026, 9, 8),
        [{'subject': 'Old', 'description': 'stale'}],
    )
    await db_session.commit()
    await replace_homework_for_day(
        db_session,
        'child1',
        date(2026, 9, 8),
        [{'subject': 'Matek', 'description': 'new'}],
    )
    await db_session.commit()
    rows = await get_homework_for_day(db_session, 'child1', date(2026, 9, 8))
    assert [r.subject for r in rows] == ['Matek']


@pytest.mark.asyncio
async def test_replace_homework_for_day_leaves_other_days_alone(db_session):
    await replace_homework_for_day(
        db_session,
        'child1',
        date(2026, 9, 7),
        [{'subject': 'Yesterday', 'description': ''}],
    )
    await replace_homework_for_day(
        db_session,
        'child1',
        date(2026, 9, 8),
        [{'subject': 'Today', 'description': ''}],
    )
    await db_session.commit()
    rows = await get_homework_for_day(db_session, 'child1', date(2026, 9, 7))
    assert [r.subject for r in rows] == ['Yesterday']


@pytest.mark.asyncio
async def test_prune_homework_before_deletes_old_rows_only(db_session):
    db_session.add(
        HomeworkEntry(
            child_id='child1',
            date=date(2020, 1, 1),
            subject='Ancient',
            description='',
            fetched_at=datetime.now(UTC),
        )
    )
    db_session.add(
        HomeworkEntry(
            child_id='child1',
            date=date(2026, 9, 8),
            subject='Recent',
            description='',
            fetched_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    await prune_homework_before(db_session, 'child1', date(2026, 8, 1))
    await db_session.commit()
    assert await get_homework_for_day(db_session, 'child1', date(2020, 1, 1)) == []
    rows = await get_homework_for_day(db_session, 'child1', date(2026, 9, 8))
    assert [r.subject for r in rows] == ['Recent']


@pytest.mark.asyncio
async def test_get_homework_for_day_orders_by_subject(db_session):
    await replace_homework_for_day(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {'subject': 'Torna', 'description': ''},
            {'subject': 'Angol', 'description': ''},
        ],
    )
    await db_session.commit()
    rows = await get_homework_for_day(db_session, 'child1', date(2026, 9, 8))
    assert [r.subject for r in rows] == ['Angol', 'Torna']
