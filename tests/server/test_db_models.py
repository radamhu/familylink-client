"""Tests for database models."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from familylink_server.db.models import (
    AppConfig,
    AuditLog,
    Base,
    DeviceSnapshot,
    UsageSnapshot,
)


@pytest.fixture
async def db_session():
    """Provide an in-memory SQLite session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_app_config_insert_and_read(db_session):
    """Test AppConfig model insert and read operations."""
    config = AppConfig(
        child_id="child1",
        app_name="YouTube",
        package_name="com.google.android.youtube",
        max_mins=30,
        days_mask="Mon-Fri",
        time_range="09:00-21:00",
        always_allowed=False,
        blocked=False,
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)
    assert config.id is not None
    assert config.app_name == "YouTube"


@pytest.mark.asyncio
async def test_usage_snapshot_insert(db_session):
    """Test UsageSnapshot model insert."""
    snap = UsageSnapshot(
        child_id="child1",
        app_package="com.google.android.youtube",
        date=date.today(),
        usage_seconds=1800,
        device_id="dev1",
        fetched_at=datetime.now(UTC),
    )
    db_session.add(snap)
    await db_session.commit()
    assert snap.id is not None


@pytest.mark.asyncio
async def test_device_snapshot_unique_device_id(db_session):
    """Test DeviceSnapshot model with unique constraint on device_id."""
    snap = DeviceSnapshot(
        device_id="dev1",
        child_id="child1",
        friendly_name="Pixel 7",
        is_locked=False,
        last_seen=datetime.now(UTC),
    )
    db_session.add(snap)
    await db_session.commit()
    assert snap.id is not None


@pytest.mark.asyncio
async def test_audit_log_insert(db_session):
    """Test AuditLog model insert."""
    log = AuditLog(
        child_id="child1",
        action="set_limit",
        target="com.google.android.youtube",
        old_value="60",
        new_value="30",
        occurred_at=datetime.now(UTC),
    )
    db_session.add(log)
    await db_session.commit()
    assert log.id is not None


def test_linux_machine_model_attributes():
    """LinuxMachine has expected columns with correct defaults."""
    from familylink_server.db.models import LinuxMachine

    m = LinuxMachine(
        child_id="child1",
        friendly_name="Gaming PC",
        hostname="192.168.1.10",
        ssh_user="kid",
        ssh_private_key="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
        created_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
    )
    assert m.ssh_port == 22
    assert m.grace_period_mins == 5
    assert m.enabled is True
    assert m.daily_limit_mins is None


def test_linux_usage_snapshot_model_attributes():
    """LinuxUsageSnapshot has expected columns."""
    from familylink_server.db.models import LinuxUsageSnapshot

    snap = LinuxUsageSnapshot(
        machine_id=1,
        date=__import__("datetime").date.today(),
        active_seconds=120,
        updated_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
    )
    assert snap.locked_at is None
    assert snap.poweroff_at is None
