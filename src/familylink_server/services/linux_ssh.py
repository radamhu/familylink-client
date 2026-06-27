"""SSH helpers for Linux machine control."""

import asyncssh


async def check_session(hostname: str, port: int, user: str, key_text: str) -> bool:
    """Return True if a graphical user session is currently active on the machine.

    Args:
        hostname: The SSH host to connect to.
        port: The SSH port number.
        user: The SSH username.
        key_text: PEM-encoded private key as a string.

    Returns:
        True if an active graphical session (on a physical seat) is detected.
    """
    key = asyncssh.import_private_key(key_text)
    async with asyncssh.connect(
        hostname,
        port=port,
        username=user,
        client_keys=[key],
        known_hosts=None,
        connect_timeout=10,
    ) as conn:
        # Check for a session bound to a physical seat (graphical login).
        # SSH-only sessions have "-" in the SEAT column and are excluded.
        result = await conn.run(
            "loginctl list-sessions --no-pager | grep -q ' seat'",
            check=False,
        )
        return result.exit_status == 0


async def lock_session(hostname: str, port: int, user: str, key_text: str) -> None:
    """Lock all active sessions on the machine.

    Args:
        hostname: The SSH host to connect to.
        port: The SSH port number.
        user: The SSH username.
        key_text: PEM-encoded private key as a string.
    """
    key = asyncssh.import_private_key(key_text)
    async with asyncssh.connect(
        hostname,
        port=port,
        username=user,
        client_keys=[key],
        known_hosts=None,
        connect_timeout=10,
    ) as conn:
        # loginctl lock-sessions requires polkit interactive auth over SSH and fails
        # silently (exit 0) on Bazzite/Fedora. Use the session D-Bus directly instead.
        await conn.run(
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus "
            "dbus-send --session --type=method_call "
            "--dest=org.freedesktop.ScreenSaver /ScreenSaver "
            "org.freedesktop.ScreenSaver.Lock",
            check=True,
        )


async def poweroff_machine(hostname: str, port: int, user: str, key_text: str) -> None:
    """Power off the machine immediately.

    Args:
        hostname: The SSH host to connect to.
        port: The SSH port number.
        user: The SSH username.
        key_text: PEM-encoded private key as a string.

    Note:
        Requires a passwordless sudo rule on the target machine:
        ``suriel ALL=(ALL) NOPASSWD: /usr/bin/systemctl poweroff``
        in /etc/sudoers.d/familylink-poweroff (chmod 440).
    """
    key = asyncssh.import_private_key(key_text)
    async with asyncssh.connect(
        hostname,
        port=port,
        username=user,
        client_keys=[key],
        known_hosts=None,
        connect_timeout=10,
    ) as conn:
        # Try D-Bus system bus first: polkit on Bazzite/Fedora allows active
        # users to call PowerOff without sudo.  Fall back to sudo for distros
        # that restrict unauthenticated D-Bus poweroff.
        result = await conn.run(
            "dbus-send --system --print-reply --dest=org.freedesktop.login1"
            " /org/freedesktop/login1"
            " 'org.freedesktop.login1.Manager.PowerOff' boolean:false",
            check=False,
        )
        if result.exit_status != 0:
            # Requires: suriel ALL=(ALL) NOPASSWD: /usr/bin/systemctl poweroff
            # in /etc/sudoers.d/familylink-poweroff (chmod 440)
            await conn.run("sudo systemctl poweroff", check=True)


async def unlock_session(hostname: str, port: int, user: str, key_text: str) -> None:
    """Unlock all sessions on the machine.

    Args:
        hostname: The SSH host to connect to.
        port: The SSH port number.
        user: The SSH username.
        key_text: PEM-encoded private key as a string.
    """
    key = asyncssh.import_private_key(key_text)
    async with asyncssh.connect(
        hostname,
        port=port,
        username=user,
        client_keys=[key],
        known_hosts=None,
        connect_timeout=10,
    ) as conn:
        # loginctl unlock-sessions has the same polkit issue as lock-sessions.
        # Kill the KDE screen locker process directly to dismiss the lock screen.
        # -f is required because kscreenlocker_greet exceeds pkill's 15-char limit.
        await conn.run("pkill -f kscreenlocker_greet || true", check=False)
