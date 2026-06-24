"""Tests that routers call DiscordNotifier after writes."""

from unittest.mock import AsyncMock, MagicMock, patch


async def test_block_app_notifies_discord(monkeypatch):
    """POST /apps/{package}/block should call DiscordNotifier.notify_change."""
    notifier = AsyncMock()
    notifier.notify_change = AsyncMock()

    svc = AsyncMock()
    member = MagicMock()
    member.user_id = "uid-1"
    member.profile.display_name = "Emma"
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    with patch("familylink_server.routers.apps.get_notifier", return_value=notifier):
        from familylink_server.routers.apps import block_app

        request = MagicMock()
        request.app.state = MagicMock()

        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        await block_app(
            package="com.tiktok",
            request=request,
            child_id="uid-1",
            _email="parent@gmail.com",
            svc=svc,
            session=session,
        )

    notifier.notify_change.assert_awaited_once()
    args = notifier.notify_change.call_args
    assert args.kwargs.get("action") == "block" or args.args[0] == "block"
    assert "web UI" in (args.kwargs.get("source", "") or str(args.args))


async def test_lock_device_notifies_discord(monkeypatch):
    """POST /devices/{device_id}/lock should call DiscordNotifier.notify_change."""
    notifier = AsyncMock()
    notifier.notify_change = AsyncMock()

    svc = AsyncMock()
    member = MagicMock()
    member.user_id = "uid-1"
    member.profile.display_name = "Emma"
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    with patch("familylink_server.routers.devices.get_notifier", return_value=notifier):
        from familylink_server.routers.devices import lock_device

        request = MagicMock()
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        await lock_device(
            device_id="d-1",
            request=request,
            child_id="uid-1",
            _email="parent@gmail.com",
            svc=svc,
            session=session,
        )

    notifier.notify_change.assert_awaited_once()
    args = notifier.notify_change.call_args
    assert args.kwargs.get("action") == "lock_device" or args.args[0] == "lock_device"
    assert "web UI" in (args.kwargs.get("source", "") or str(args.args))


async def test_set_limit_notifies_discord(monkeypatch):
    """POST /apps/{package}/limit should call DiscordNotifier.notify_change."""
    notifier = AsyncMock()
    notifier.notify_change = AsyncMock()

    svc = AsyncMock()
    member = MagicMock()
    member.user_id = "uid-1"
    member.profile.display_name = "Emma"
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    with patch("familylink_server.routers.apps.get_notifier", return_value=notifier):
        from familylink_server.routers.apps import set_limit

        request = MagicMock()
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        await set_limit(
            package="com.example.app",
            request=request,
            child_id="uid-1",
            minutes=60,
            _email="parent@gmail.com",
            svc=svc,
            session=session,
        )

    notifier.notify_change.assert_awaited_once()
    args = notifier.notify_change.call_args
    assert args.kwargs.get("action") == "set_limit" or args.args[0] == "set_limit"
    assert "web UI" in (args.kwargs.get("source", "") or str(args.args))


async def test_unlock_device_notifies_discord(monkeypatch):
    """POST /devices/{device_id}/unlock should call DiscordNotifier.notify_change."""
    notifier = AsyncMock()
    notifier.notify_change = AsyncMock()

    svc = AsyncMock()
    member = MagicMock()
    member.user_id = "uid-1"
    member.profile.display_name = "Emma"
    member.member_supervision_info.is_supervised_member = True
    svc.get_members.return_value = MagicMock(members=[member])

    with patch("familylink_server.routers.devices.get_notifier", return_value=notifier):
        from familylink_server.routers.devices import unlock_device

        request = MagicMock()
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        await unlock_device(
            device_id="d-1",
            request=request,
            child_id="uid-1",
            _email="parent@gmail.com",
            svc=svc,
            session=session,
        )

    notifier.notify_change.assert_awaited_once()
    args = notifier.notify_change.call_args
    assert (
        args.kwargs.get("action") == "unlock_device" or args.args[0] == "unlock_device"
    )
    assert "web UI" in (args.kwargs.get("source", "") or str(args.args))


async def test_no_notify_when_notifier_is_none(monkeypatch):
    """Router writes should complete without error when get_notifier returns None."""
    svc = AsyncMock()
    member = MagicMock()
    member.user_id = "uid-1"
    member.profile.display_name = "Emma"
    svc.get_members.return_value = MagicMock(members=[member])

    with patch("familylink_server.routers.apps.get_notifier", return_value=None):
        from familylink_server.routers.apps import allow_app

        request = MagicMock()
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        # Should not raise
        await allow_app(
            package="com.example.app",
            request=request,
            child_id="uid-1",
            _email="parent@gmail.com",
            svc=svc,
            session=session,
        )

    # If we got here, no exception was raised — pass
