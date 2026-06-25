"""SQLAlchemy ORM models."""

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""


class AppConfig(Base):
    """App configuration settings for a child's device usage."""

    __tablename__ = "app_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_name: Mapped[str] = mapped_column(String(256), nullable=False)
    package_name: Mapped[str] = mapped_column(String(256), nullable=False)
    max_mins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_mask: Mapped[str] = mapped_column(String(64), default="")
    time_range: Mapped[str] = mapped_column(String(32), default="")
    always_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class UsageSnapshot(Base):
    """Snapshot of app usage on a specific date."""

    __tablename__ = "usage_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_package: Mapped[str] = mapped_column(String(256), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    usage_seconds: Mapped[int] = mapped_column(Integer, default=0)
    device_id: Mapped[str] = mapped_column(String(128), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeviceSnapshot(Base):
    """Snapshot of device state and metadata."""

    __tablename__ = "device_snapshots"
    __table_args__ = (UniqueConstraint("device_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False)
    friendly_name: Mapped[str] = mapped_column(String(256), default="")
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Audit trail of administrative actions on child accounts."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(256), default="")
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LinuxMachine(Base):
    """Registered Linux machine managed via SSH."""

    __tablename__ = "linux_machines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[str] = mapped_column(String(64), nullable=False)
    friendly_name: Mapped[str] = mapped_column(String(256), nullable=False)
    hostname: Mapped[str] = mapped_column(String(256), nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_user: Mapped[str] = mapped_column(String(64), nullable=False)
    ssh_private_key: Mapped[str] = mapped_column(Text, nullable=False)
    daily_limit_mins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grace_period_mins: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __init__(self, **kwargs: object) -> None:
        """Initialise with Python-level defaults for optional columns."""
        kwargs.setdefault("ssh_port", 22)
        kwargs.setdefault("grace_period_mins", 5)
        kwargs.setdefault("enabled", True)
        kwargs.setdefault("daily_limit_mins", None)
        super().__init__(**kwargs)


class LinuxUsageSnapshot(Base):
    """Daily active-session accumulator for a Linux machine."""

    __tablename__ = "linux_usage_snapshots"
    __table_args__ = (UniqueConstraint("machine_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("linux_machines.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    active_seconds: Mapped[int] = mapped_column(Integer, default=0)
    bonus_mins: Mapped[int] = mapped_column(Integer, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    poweroff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __init__(self, **kwargs: object) -> None:
        """Initialise with Python-level defaults for optional columns."""
        kwargs.setdefault("active_seconds", 0)
        kwargs.setdefault("bonus_mins", 0)
        kwargs.setdefault("locked_at", None)
        kwargs.setdefault("poweroff_at", None)
        super().__init__(**kwargs)
