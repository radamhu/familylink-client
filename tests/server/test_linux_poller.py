"""Tests for the Linux machine poller."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo('Europe/Budapest')


def test_in_window_same_day_range():
    """Start inclusive, end exclusive, for a same-day window."""
    from familylink_server.services.linux_poller import _in_window

    start, end = datetime.time(9, 0), datetime.time(15, 0)
    assert _in_window(datetime.time(9, 0), start, end) is True
    assert _in_window(datetime.time(12, 0), start, end) is True
    assert _in_window(datetime.time(8, 59), start, end) is False
    assert _in_window(datetime.time(15, 0), start, end) is False


def test_in_window_overnight_wrap():
    """Start > end wraps past midnight, e.g. bedtime 21:00-07:00."""
    from familylink_server.services.linux_poller import _in_window

    start, end = datetime.time(21, 0), datetime.time(7, 0)
    assert _in_window(datetime.time(21, 0), start, end) is True
    assert _in_window(datetime.time(23, 30), start, end) is True
    assert _in_window(datetime.time(3, 0), start, end) is True
    assert _in_window(datetime.time(6, 59), start, end) is True
    assert _in_window(datetime.time(7, 0), start, end) is False
    assert _in_window(datetime.time(12, 0), start, end) is False


def test_in_window_disabled_when_either_bound_missing():
    """Either bound unset means no window is enforced."""
    from familylink_server.services.linux_poller import _in_window

    assert _in_window(datetime.time(22, 0), None, datetime.time(7, 0)) is False
    assert _in_window(datetime.time(22, 0), datetime.time(21, 0), None) is False
    assert _in_window(datetime.time(22, 0), None, None) is False


def test_in_window_equal_start_end_never_blocks():
    """Equal start/end is treated as a disabled window, not a 24h block."""
    from familylink_server.services.linux_poller import _in_window

    assert (
        _in_window(datetime.time(21, 0), datetime.time(21, 0), datetime.time(21, 0))
        is False
    )


def test_shift_time_later_within_day():
    """Shifting by bonus minutes moves the time forward without wrapping."""
    from familylink_server.services.linux_poller import _shift_time_later

    assert _shift_time_later(datetime.time(21, 0), 45) == datetime.time(21, 45)
    assert _shift_time_later(datetime.time(21, 0), 0) == datetime.time(21, 0)


def test_shift_time_later_wraps_past_midnight():
    """Shifting past midnight wraps to the next day's time-of-day."""
    from familylink_server.services.linux_poller import _shift_time_later

    assert _shift_time_later(datetime.time(23, 45), 30) == datetime.time(0, 15)


def _make_machine(
    machine_id: int = 1,
    daily_limit_mins: int | None = 60,
    grace_period_mins: int = 5,
    hostname: str = 'host',
    ssh_port: int = 22,
    ssh_user: str = 'user',
    ssh_private_key: str = 'key',
    friendly_name: str = 'Test PC',
    window_start_time: datetime.time | None = None,
    window_end_time: datetime.time | None = None,
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
    m.window_start_time = window_start_time
    m.window_end_time = window_end_time
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
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch(
            'familylink_server.services.linux_poller.make_session',
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
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=False),
        ),
        patch(
            'familylink_server.services.linux_poller.make_session',
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
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', mock_lock),
        patch(
            'familylink_server.services.linux_poller.make_session',
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
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', mock_lock),
        patch('familylink_server.services.linux_poller.poweroff_machine', AsyncMock()),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    mock_lock.assert_awaited_once()
    assert snapshot.locked_at == locked_ts, 'locked_at must not change on re-lock'


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
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=False),
        ),
        patch(
            'familylink_server.services.linux_poller.poweroff_machine', mock_poweroff
        ),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    mock_poweroff.assert_awaited_once()
    assert snapshot.poweroff_at is not None


async def test_poll_machine_clears_poweroff_state_on_reboot_detection():
    """When poweroff_at is set but SSH succeeds, the machine rebooted.

    Only poweroff_at is cleared so the poller can re-attempt shutdown.
    locked_at is preserved: its elapsed time already exceeds the grace period,
    so poweroff fires on the same tick — no free window for the child.
    check_session IS called — we need SSH to detect the reboot.
    """
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=None)
    now = datetime.datetime.now(datetime.UTC)
    original_locked_at = now - datetime.timedelta(hours=1)
    snapshot = _make_snapshot(locked_at=original_locked_at, poweroff_at=now)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_check = AsyncMock(return_value=False)  # no active graphical session yet
    mock_poweroff = AsyncMock()
    with (
        patch('familylink_server.services.linux_poller.check_session', mock_check),
        patch(
            'familylink_server.services.linux_poller.poweroff_machine', mock_poweroff
        ),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    mock_check.assert_awaited_once()
    # poweroff fires immediately: elapsed (1 h) already exceeds grace period
    mock_poweroff.assert_awaited_once()
    assert snapshot.locked_at == original_locked_at  # preserved — no free grace window


async def test_poll_machine_logs_warning_on_ssh_failure():
    """SSH failure is caught and logged; no exception propagates."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine()
    snapshot = _make_snapshot(active_seconds=0)  # locked_at=None → no poweroff written
    mock_ctx, _ = _make_session_ctx(snapshot)

    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(side_effect=ConnectionError('timeout')),
        ),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)  # must not raise


async def test_poll_machine_marks_poweroff_when_locked_and_ssh_fails():
    """When SSH fails and machine was locked, poweroff_at is set.

    Prevents the UI from showing 'locked' indefinitely when a child bypasses the
    lock screen by physically holding the power button — a state the poller cannot
    reach via its normal enforcement path.
    """
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine()
    locked_ts = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=2)
    snapshot = _make_snapshot(locked_at=locked_ts)  # locked but not yet powered off
    mock_ctx, mock_session = _make_session_ctx(snapshot)

    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(side_effect=ConnectionError('timeout')),
        ),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine)

    assert snapshot.poweroff_at is not None
    mock_session.commit.assert_awaited_once()


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
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', mock_lock),
        patch(
            'familylink_server.services.linux_poller.make_session',
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
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', AsyncMock()),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, notifier=mock_notifier)

    mock_notifier.notify_change.assert_awaited_once_with(
        'lock_linux', machine.child_id, machine.friendly_name, 'poller'
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
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=False),
        ),
        patch('familylink_server.services.linux_poller.poweroff_machine', AsyncMock()),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, notifier=mock_notifier)

    mock_notifier.notify_change.assert_awaited_once_with(
        'poweroff_linux', machine.child_id, machine.friendly_name, 'poller'
    )


async def test_poll_machine_locks_when_in_window_regardless_of_usage():
    """A machine inside its bedtime window locks even with no daily cap set."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(
        daily_limit_mins=None,
        window_start_time=datetime.time(21, 0),
        window_end_time=datetime.time(7, 0),
    )
    snapshot = _make_snapshot(active_seconds=0)
    mock_ctx, _ = _make_session_ctx(snapshot)
    # Window bounds are household wall-clock; tag `now` with that same tz so
    # the injected value means what it says.
    now = datetime.datetime(2026, 1, 1, 22, 0, tzinfo=LOCAL_TZ)

    mock_lock = AsyncMock()
    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', mock_lock),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, now=now)

    mock_lock.assert_awaited_once()
    assert snapshot.locked_at is not None


async def test_poll_machine_bonus_shifts_window_start_later():
    """bonus_mins delays the window's effective start, same lever as the usage cap."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(
        daily_limit_mins=None,
        window_start_time=datetime.time(21, 0),
        window_end_time=datetime.time(23, 0),
    )
    snapshot = _make_snapshot(active_seconds=0, bonus_mins=30)
    mock_ctx, _ = _make_session_ctx(snapshot)
    # 21:15 local is before the bonus-shifted start of 21:30 — should not lock.
    now = datetime.datetime(2026, 1, 1, 21, 15, tzinfo=LOCAL_TZ)

    mock_lock = AsyncMock()
    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', mock_lock),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, now=now)

    mock_lock.assert_not_awaited()


async def test_poll_machine_does_not_autounlock_while_in_window():
    """Being under the usage cap does not unlock a machine still inside its window."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(
        daily_limit_mins=None,
        grace_period_mins=5,
        window_start_time=datetime.time(21, 0),
        window_end_time=datetime.time(23, 0),
    )
    now = datetime.datetime(2026, 1, 1, 22, 0, tzinfo=LOCAL_TZ)
    locked_ts = now - datetime.timedelta(
        minutes=1
    )  # under grace period, no poweroff yet
    snapshot = _make_snapshot(active_seconds=0, locked_at=locked_ts)
    mock_ctx, _ = _make_session_ctx(snapshot)

    mock_unlock = AsyncMock()
    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', AsyncMock()),
        patch('familylink_server.services.linux_poller.unlock_session', mock_unlock),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, now=now)

    mock_unlock.assert_not_awaited()
    assert snapshot.locked_at == locked_ts


async def test_poll_machine_no_crash_when_notifier_is_none():
    """poll_machine does not crash when notifier=None and lock is applied."""
    from familylink_server.services.linux_poller import poll_machine

    machine = _make_machine(daily_limit_mins=1)
    snapshot = _make_snapshot(active_seconds=60, bonus_mins=0)
    mock_ctx, _ = _make_session_ctx(snapshot)

    with (
        patch(
            'familylink_server.services.linux_poller.check_session',
            AsyncMock(return_value=True),
        ),
        patch('familylink_server.services.linux_poller.lock_session', AsyncMock()),
        patch(
            'familylink_server.services.linux_poller.make_session',
            return_value=mock_ctx,
        ),
    ):
        await poll_machine(machine, notifier=None)  # must not raise
