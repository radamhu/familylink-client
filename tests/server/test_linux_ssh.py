"""Tests for SSH helpers in linux_ssh.py."""

from unittest.mock import AsyncMock, MagicMock, patch


def _make_ssh_mock(stdout: str) -> tuple:
    """Return (mock_conn, mock_context_manager) for asyncssh.connect."""
    mock_result = MagicMock(stdout=stdout, exit_status=0)
    mock_conn = MagicMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_conn, mock_cm


async def test_check_session_returns_true_when_active():
    """check_session returns True when loginctl output contains 'active'."""
    from familylink_server.services.linux_ssh import check_session

    _, mock_cm = _make_ssh_mock("5 1000 user seat0 :0 active")
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


async def test_check_session_falls_back_to_who():
    """check_session falls back to 'who' if loginctl has no 'active'."""
    from familylink_server.services.linux_ssh import check_session

    mock_result_loginctl = MagicMock(stdout="no sessions", exit_status=0)
    mock_result_who = MagicMock(
        stdout="kid  tty7  2026-06-25 10:00 (:0)", exit_status=0
    )
    mock_conn = MagicMock()
    mock_conn.run = AsyncMock(side_effect=[mock_result_loginctl, mock_result_who])
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

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


async def test_check_session_returns_false_when_no_session():
    """check_session returns False when both loginctl and who show no session."""
    from familylink_server.services.linux_ssh import check_session

    mock_result = MagicMock(stdout="", exit_status=0)
    mock_conn = MagicMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

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


async def test_lock_session_runs_loginctl():
    """lock_session issues loginctl lock-sessions over SSH."""
    from familylink_server.services.linux_ssh import lock_session

    mock_conn, mock_cm = _make_ssh_mock("")
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
    mock_conn.run.assert_awaited_once_with("loginctl lock-sessions", check=False)


async def test_poweroff_machine_runs_systemctl():
    """poweroff_machine issues systemctl poweroff over SSH."""
    from familylink_server.services.linux_ssh import poweroff_machine

    mock_conn, mock_cm = _make_ssh_mock("")
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
    mock_conn.run.assert_awaited_once_with("systemctl poweroff", check=False)
