"""Tests for homework_entries/ekreta_credentials DB helpers (real in-memory DB)."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from familylink_server.db.homework import (
    get_upcoming_homework,
    list_ekreta_credentials,
    prune_expired_homework,
    upsert_homework_entries,
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
async def test_upsert_inserts_new_entry(db_session):
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {
                'subject': 'Matek',
                'deadline': date(2026, 9, 10),
                'description': 'new',
            }
        ],
    )
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2026, 9, 8))
    assert [(r.subject, r.description) for r in rows] == [('Matek', 'new')]


@pytest.mark.asyncio
async def test_upsert_refreshes_existing_entry_same_identity(db_session):
    """Same (child_id, subject, deadline) scraped again refreshes, not duplicates."""
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [{'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'stale'}],
    )
    await db_session.commit()
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 9),
        [{'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'fresh'}],
    )
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2026, 9, 8))
    assert [(r.subject, r.description, r.date) for r in rows] == [
        ('Matek', 'fresh', date(2026, 9, 9))
    ]


@pytest.mark.asyncio
async def test_upsert_keeps_distinct_subject_same_deadline_separate(db_session):
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'a'},
            {'subject': 'Angol', 'deadline': date(2026, 9, 10), 'description': 'b'},
        ],
    )
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2026, 9, 8))
    assert sorted(r.subject for r in rows) == ['Angol', 'Matek']


@pytest.mark.asyncio
async def test_prune_expired_homework_deletes_past_deadline_only(db_session):
    db_session.add(
        HomeworkEntry(
            child_id='child1',
            date=date(2026, 9, 1),
            deadline=date(2026, 9, 7),
            subject='Old',
            description='',
            fetched_at=datetime.now(UTC),
        )
    )
    db_session.add(
        HomeworkEntry(
            child_id='child1',
            date=date(2026, 9, 8),
            deadline=date(2026, 9, 10),
            subject='Recent',
            description='',
            fetched_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    await prune_expired_homework(db_session, 'child1', date(2026, 9, 8))
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2020, 1, 1))
    assert [r.subject for r in rows] == ['Recent']


@pytest.mark.asyncio
async def test_get_upcoming_homework_excludes_past_deadlines(db_session):
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {'subject': 'Past', 'deadline': date(2026, 9, 7), 'description': ''},
            {'subject': 'Today', 'deadline': date(2026, 9, 8), 'description': ''},
            {'subject': 'Future', 'deadline': date(2026, 9, 9), 'description': ''},
        ],
    )
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2026, 9, 8))
    assert [r.subject for r in rows] == ['Today', 'Future']


@pytest.mark.asyncio
async def test_get_upcoming_homework_orders_by_deadline_then_subject(db_session):
    await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {'subject': 'Torna', 'deadline': date(2026, 9, 9), 'description': ''},
            {'subject': 'Angol', 'deadline': date(2026, 9, 9), 'description': ''},
            {'subject': 'Matek', 'deadline': date(2026, 9, 8), 'description': ''},
        ],
    )
    await db_session.commit()
    rows = await get_upcoming_homework(db_session, 'child1', date(2026, 9, 8))
    assert [r.subject for r in rows] == ['Matek', 'Angol', 'Torna']


@pytest.mark.asyncio
async def test_upsert_returns_only_newly_created_entries(db_session):
    """First call: both entries are new. Second call, one repeated + one new:
    only the genuinely new one comes back.
    """
    new_entries = await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 8),
        [
            {'subject': 'Matek', 'deadline': date(2026, 9, 10), 'description': 'a'},
            {'subject': 'Angol', 'deadline': date(2026, 9, 10), 'description': 'b'},
        ],
    )
    await db_session.commit()
    assert sorted(e['subject'] for e in new_entries) == ['Angol', 'Matek']

    more_entries = await upsert_homework_entries(
        db_session,
        'child1',
        date(2026, 9, 9),
        [
            {
                'subject': 'Matek',
                'deadline': date(2026, 9, 10),
                'description': 'refreshed',
            },
            {'subject': 'Torna', 'deadline': date(2026, 9, 11), 'description': 'c'},
        ],
    )
    await db_session.commit()
    assert [e['subject'] for e in more_entries] == ['Torna']
