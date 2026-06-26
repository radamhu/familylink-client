"""Tests for SSH helpers in linux_ssh.py."""

from unittest.mock import AsyncMock, MagicMock, patch

_LOCK_CMD = (
    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus "
    "dbus-send --session --type=method_call "
    "--dest=org.freedesktop.ScreenSaver /ScreenSaver "
    "org.freedesktop.ScreenSaver.Lock"
)
_CHECK_CMD = "loginctl list-sessions --no-pager | grep -q ' seat'"


def _make_ssh_mock(exit_status: int = 0) -> tuple:
    """Return (mock_conn, mock_context_manager) for asyncssh.connect."""
    mock_result = MagicMock(exit_status=exit_status)
    mock_conn = MagicMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_conn, mock_cm


async def test_check_session_returns_true_when_seat_session_active():
    """check_session returns True when a graphical (seat-based) session exists."""
    from familylink_server.services.linux_ssh import check_session

    mock_conn, mock_cm = _make_ssh_mock(exit_status=0)
    with (
        patch(
            "familylink_server.services.linux_ssh.asyncssh.import_private_key",
            return_value=MagicMock(),
        ),
        patch(
            "familylink_server.services.linux_ssh.asyncssh.connect",
            return_value=mock_cm,
        ),
    ):
        result = await check_session("host", 22, "user", "fake-pem")
    assert result is True
    mock_conn.run.assert_awaited_once_with(_CHECK_CMD, check=False)


async def test_check_session_returns_false_when_no_seat_session():
    """check_session returns False when only SSH/system sessions exist (no graphical seat)."""
    from familylink_server.services.linux_ssh import check_session

    mock_conn, mock_cm = _make_ssh_mock(exit_status=1)
    with (
        patch(
            "familylink_server.services.linux_ssh.asyncssh.import_private_key",
            return_value=MagicMock(),
        ),
        patch(
            "familylink_server.services.linux_ssh.asyncssh.connect",
            return_value=mock_cm,
        ),
    ):
        result = await check_session("host", 22, "user", "fake-pem")
    assert result is False
    mock_conn.run.assert_awaited_once_with(_CHECK_CMD, check=False)


async def test_lock_session_runs_dbus_send():
    """lock_session uses dbus-send via session bus (loginctl lock-sessions fails on Bazzite)."""
    from familylink_server.services.linux_ssh import lock_session

    mock_conn, mock_cm = _make_ssh_mock()
    with (
        patch(
            "familylink_server.services.linux_ssh.asyncssh.import_private_key",
            return_value=MagicMock(),
        ),
        patch(
            "familylink_server.services.linux_ssh.asyncssh.connect",
            return_value=mock_cm,
        ),
    ):
        await lock_session("host", 22, "user", "fake-pem")
    mock_conn.run.assert_awaited_once_with(_LOCK_CMD, check=True)


async def test_poweroff_machine_runs_sudo_systemctl():
    """poweroff_machine issues sudo systemctl poweroff over SSH."""
    from familylink_server.services.linux_ssh import poweroff_machine

    mock_conn, mock_cm = _make_ssh_mock()
    with (
        patch(
            "familylink_server.services.linux_ssh.asyncssh.import_private_key",
            return_value=MagicMock(),
        ),
        patch(
            "familylink_server.services.linux_ssh.asyncssh.connect",
            return_value=mock_cm,
        ),
    ):
        await poweroff_machine("host", 22, "user", "fake-pem")
    mock_conn.run.assert_awaited_once_with("sudo systemctl poweroff", check=False)


async def test_unlock_session_kills_kscreenlocker():
    """unlock_session kills the KDE screen locker process (loginctl unlock-sessions fails on Bazzite)."""
    from familylink_server.services.linux_ssh import unlock_session

    mock_conn, mock_cm = _make_ssh_mock()
    with (
        patch(
            "familylink_server.services.linux_ssh.asyncssh.import_private_key",
            return_value=MagicMock(),
        ),
        patch(
            "familylink_server.services.linux_ssh.asyncssh.connect",
            return_value=mock_cm,
        ),
    ):
        await unlock_session("host", 22, "user", "fake-pem")
    mock_conn.run.assert_awaited_once_with(
        "pkill -f kscreenlocker_greet || true", check=False
    )
