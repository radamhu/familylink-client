"""SSH helpers for Linux machine control."""

import asyncssh


async def check_session(hostname: str, port: int, user: str, key_text: str) -> bool:
    """Return True if a user session is currently active on the machine.

    Args:
        hostname: The SSH host to connect to.
        port: The SSH port number.
        user: The SSH username.
        key_text: PEM-encoded private key as a string.

    Returns:
        True if an active session is detected, False otherwise.
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
        result = await conn.run("loginctl list-sessions --no-pager", check=False)
        if "active" in result.stdout:
            return True
        result2 = await conn.run("who", check=False)
        return bool(result2.stdout.strip())


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
        await conn.run("loginctl lock-sessions", check=False)


async def poweroff_machine(hostname: str, port: int, user: str, key_text: str) -> None:
    """Power off the machine immediately.

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
        await conn.run("systemctl poweroff", check=False)


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
        await conn.run("loginctl unlock-sessions", check=False)
