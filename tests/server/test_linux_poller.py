"""Tests for the Linux machine poller."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_machine(
    machine_id: int = 1,
    daily_limit_mins: int | None = 60,
    grace_period_mins: int = 5,
    hostname: str = "host",
    ssh_port: int = 22,
    ssh_user: str = "user",
    ssh_private_key: str = "key",
    friendly_name: str = "Test PC",
) -> MagicMock:
    m = MagicMock()
    m.id = machine_id
    m.hostname = hostname
    m.ssh_port = ssh_port
    m.ssh_user = ssh_user
    m.ssh_private_key = ssh_private_key
    m.friendly_name = friendly_name
    m.daily_limit_mins = daily_limit_mins
    m.grace_period_mins = grace_period_mins
    return m


def _make_snapshot(
    active_seconds: int = 0,
    locked_at: datetime.datetime | None = None,
    poweroff_at: datetime.datetime | None = None,
    bonus_mins: int = 0,
) -> MagicMock:
    snap = MagicMock()
    snap.active_seconds = active_seconds
    snap.locked_at = locked_at
    snap.poweroff_at = poweroff_at
    snap.bonus_mins = bonus_mins
    snap.updated_at = None
    return snap


def _make_session_ctx(snapshot: MagicMock | None) -> MagicMock:
    """Build a mock async context manager that returns snapshot from scalar_one_or_none."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=snapshot))
    )
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx, mock_session


async def test_poll_machine_increments_active_seconds_when_session_active():
    """Active session increments active_seconds by 60."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=None)
    snapshot = _make_snapshot(active_seconds=0)
    mock_ctx, mock_session = _make_session_ctx(snapshot)

    with (
        patch(
            "familylink_server.services.linux_poller.check_session",
            AsyncMock(return_value=True),
        ),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    assert snapshot.active_seconds == 60
    mock_session.commit.assert_awaited_once()


async def test_poll_machine_does_not_increment_when_session_idle():
    """Idle session leaves active_seconds unchanged."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=None)
    snapshot = _make_snapshot(active_seconds=100)
    mock_ctx, mock_session = _make_session_ctx(snapshot)

    with (
        patch(
            "familylink_server.services.linux_poller.check_session",
            AsyncMock(return_value=False),
        ),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    assert snapshot.active_seconds == 100


async def test_poll_machine_applies_soft_lock_when_limit_reached():
    """lock_session is called and locked_at is set when active_seconds >= limit."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)  # 60 s limit
    snapshot = _make_snapshot(active_seconds=60)  # exactly at limit
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_lock = AsyncMock()
    with (
        patch(
            "familylink_server.services.linux_poller.check_session",
            AsyncMock(return_value=True),
        ),
        patch("familylink_server.services.linux_poller.lock_session", mock_lock),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    mock_lock.assert_awaited_once()
    assert snapshot.locked_at is not None


async def test_poll_machine_relocks_when_user_dismisses_lock():
    """lock_session IS called again on every poll when already locked and still over limit.

    The child can dismiss a D-Bus screensaver lock from the keyboard; the poller
    must re-apply it on the next tick rather than leaving the machine unguarded.
    locked_at must NOT be updated so the grace-period timer is preserved.
    """
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)
    locked_ts = datetime.datetime.now(datetime.UTC)
    snapshot = _make_snapshot(active_seconds=120, locked_at=locked_ts)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_lock = AsyncMock()
    with (
        patch(
            "familylink_server.services.linux_poller.check_session",
            AsyncMock(return_value=True),
        ),
        patch("familylink_server.services.linux_poller.lock_session", mock_lock),
        patch("familylink_server.services.linux_poller.poweroff_machine", AsyncMock()),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    mock_lock.assert_awaited_once()
    assert snapshot.locked_at == locked_ts, "locked_at must not change on re-lock"


async def test_poll_machine_powers_off_after_grace_period():
    """poweroff_machine is called after grace_period_mins have elapsed since locked_at."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1, grace_period_mins=5)
    # locked 6 minutes ago — grace period exceeded
    locked_ts = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=6)
    snapshot = _make_snapshot(active_seconds=120, locked_at=locked_ts)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_poweroff = AsyncMock()
    with (
        patch(
            "familylink_server.services.linux_poller.check_session",
            AsyncMock(return_value=False),
        ),
        patch(
            "familylink_server.services.linux_poller.poweroff_machine", mock_poweroff
        ),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    mock_poweroff.assert_awaited_once()
    assert snapshot.poweroff_at is not None


async def test_poll_machine_clears_poweroff_state_on_reboot_detection():
    """When poweroff_at is set but SSH succeeds, the machine rebooted.

    The poller must clear poweroff_at/locked_at so the normal limit enforcement
    cycle restarts.  check_session IS called — we need SSH to detect the reboot.
    """
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=None)
    now = datetime.datetime.now(datetime.UTC)
    snapshot = _make_snapshot(locked_at=now, poweroff_at=now)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_check = AsyncMock(return_value=False)  # no active graphical session yet
    with (
        patch("familylink_server.services.linux_poller.check_session", mock_check),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    mock_check.assert_awaited_once()
    assert snapshot.poweroff_at is None
    assert snapshot.locked_at is None


async def test_poll_machine_logs_warning_on_ssh_failure():
    """SSH failure is caught and logged; no exception propagates."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine()
    # No poweroff_at on existing snapshot → poll proceeds to SSH
    snapshot = _make_snapshot(active_seconds=0)
    mock_ctx, _ = _make_session_ctx(snapshot)

    with (
        patch(
            "familylink_server.services.linux_poller.check_session",
            AsyncMock(side_effect=ConnectionError("timeout")),
        ),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)  # must not raise


async def test_poll_machine_respects_bonus_mins_in_effective_limit():
    """Bonus mins extend the limit — machine is not locked when under effective threshold."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)  # 60 s limit
    # bonus_mins=1 → effective limit = 2 min = 120 s; active=59 s + 60 poll = 119 s → below threshold
    snapshot = _make_snapshot(active_seconds=59, bonus_mins=1)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_lock = AsyncMock()
    with (
        patch(
            "familylink_server.services.linux_poller.check_session",
            AsyncMock(return_value=True),
        ),
        patch("familylink_server.services.linux_poller.lock_session", mock_lock),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    mock_lock.assert_not_awaited()


async def test_poll_machine_notifies_on_soft_lock():
    """notify_change called with 'lock_linux' when soft lock is applied."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)
    snapshot = _make_snapshot(active_seconds=60, bonus_mins=0)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_notifier = AsyncMock()
    with (
        patch(
            "familylink_server.services.linux_poller.check_session",
            AsyncMock(return_value=True),
        ),
        patch("familylink_server.services.linux_poller.lock_session", AsyncMock()),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, notifier=mock_notifier)

    mock_notifier.notify_change.assert_awaited_once_with(
        "lock_linux", machine.child_id, machine.friendly_name, "poller"
    )


async def test_poll_machine_notifies_on_poweroff():
    """notify_change called with 'poweroff_linux' when poweroff is applied."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1, grace_period_mins=5)
    locked_ts = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=6)
    snapshot = _make_snapshot(active_seconds=120, locked_at=locked_ts, bonus_mins=0)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_notifier = AsyncMock()
    with (
        patch(
            "familylink_server.services.linux_poller.check_session",
            AsyncMock(return_value=False),
        ),
        patch("familylink_server.services.linux_poller.poweroff_machine", AsyncMock()),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, notifier=mock_notifier)

    mock_notifier.notify_change.assert_awaited_once_with(
        "poweroff_linux", machine.child_id, machine.friendly_name, "poller"
    )


async def test_poll_machine_no_crash_when_notifier_is_none():
    """poll_machine does not crash when notifier=None and lock is applied."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)
    snapshot = _make_snapshot(active_seconds=60, bonus_mins=0)
    mock_ctx, _ = _make_session_ctx(snapshot)

    with (
        patch(
            "familylink_server.services.linux_poller.check_session",
            AsyncMock(return_value=True),
        ),
        patch("familylink_server.services.linux_poller.lock_session", AsyncMock()),
        patch(
            "familylink_server.services.linux_poller.make_session",
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, notifier=None)  # must not raise
