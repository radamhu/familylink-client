"""Tests for /linux-machines router."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer

from familylink_server.config import settings
from familylink_server.db import get_session


def _cookie() -> str:
    s = URLSafeSerializer(settings.secret_key, salt="fl-session")
    return s.dumps({"email": settings.familylink_google_email})


def _mock_svc(children: list | None = None) -> MagicMock:
    children = children or []
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=children))
    return mock_svc


def _mock_session(
    machines: list | None = None, machine: MagicMock | None = None
) -> MagicMock:
    """Build a mock AsyncSession that returns machines from execute() and machine from get()."""
    machines = machines or []
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = machines
    mock_exec_result.scalar_one_or_none.return_value = None

    mock_s = AsyncMock()
    mock_s.execute = AsyncMock(return_value=mock_exec_result)
    mock_s.get = AsyncMock(return_value=machine)
    mock_s.add = MagicMock()
    mock_s.flush = AsyncMock()
    mock_s.commit = AsyncMock()
    mock_s.delete = AsyncMock()
    return mock_s


def test_linux_machines_page_returns_200():
    """GET /linux-machines with auth returns 200."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session()
    try:
        client = TestClient(app)
        resp = client.get("/linux-machines", cookies={"fl_session": _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200


def test_linux_machines_page_requires_auth():
    """GET /linux-machines without auth returns 401."""
    from familylink_server.main import app

    client = TestClient(app, follow_redirects=False)
    resp = client.get("/linux-machines")
    assert resp.status_code == 401


def test_create_machine_redirects():
    """POST /linux-machines creates machine and redirects to list."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session()
    try:
        client = TestClient(app, follow_redirects=False)
        resp = client.post(
            "/linux-machines",
            data={
                "friendly_name": "Test PC",
                "child_id": "child1",
                "hostname": "192.168.1.10",
                "ssh_port": "22",
                "ssh_user": "kid",
                "ssh_private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
                "grace_period_mins": "5",
            },
            cookies={"fl_session": _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/linux-machines"


def test_lock_machine_returns_partial_html():
    """POST /linux-machines/{id}/lock returns HTML partial with 'locked'."""
    from unittest.mock import patch

    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.hostname = "host"
    mock_machine.ssh_port = 22
    mock_machine.ssh_user = "user"
    mock_machine.ssh_private_key = "key"
    mock_machine.friendly_name = "Test PC"
    mock_machine.child_id = "child1"
    mock_machine.daily_limit_mins = 60
    mock_machine.grace_period_mins = 5

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session(machine=mock_machine)
    try:
        client = TestClient(app)
        with patch(
            "familylink_server.routers.linux_machines.lock_session", AsyncMock()
        ):
            resp = client.post(
                "/linux-machines/1/lock",
                cookies={"fl_session": _cookie()},
            )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert "locked" in resp.text.lower()


def test_poweroff_machine_returns_partial_html():
    """POST /linux-machines/{id}/poweroff returns HTML partial with 'powered'."""
    from unittest.mock import patch

    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.hostname = "host"
    mock_machine.ssh_port = 22
    mock_machine.ssh_user = "user"
    mock_machine.ssh_private_key = "key"
    mock_machine.friendly_name = "Test PC"
    mock_machine.child_id = "child1"
    mock_machine.daily_limit_mins = 60
    mock_machine.grace_period_mins = 5

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session(machine=mock_machine)
    try:
        client = TestClient(app)
        with patch(
            "familylink_server.routers.linux_machines.poweroff_machine", AsyncMock()
        ):
            resp = client.post(
                "/linux-machines/1/poweroff",
                cookies={"fl_session": _cookie()},
            )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert "powered" in resp.text.lower()


def test_delete_machine_returns_empty():
    """DELETE /linux-machines/{id} returns empty 200 for HTMX removal."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session(machine=mock_machine)
    try:
        client = TestClient(app)
        resp = client.delete(
            "/linux-machines/1",
            cookies={"fl_session": _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert resp.text == ""


def test_generate_key_returns_key_pair():
    """POST /linux-machines/generate-key returns private and public key strings."""
    from familylink_server.main import app

    client = TestClient(app)
    resp = client.post(
        "/linux-machines/generate-key",
        cookies={"fl_session": _cookie()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["private_key"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert "ssh-ed25519" in data["public_key"]


def test_generate_key_requires_auth():
    """POST /linux-machines/generate-key without auth returns 401."""
    from familylink_server.main import app

    client = TestClient(app)
    resp = client.post("/linux-machines/generate-key")
    assert resp.status_code == 401


def test_bonus_adds_minutes_and_returns_card():
    """POST /linux-machines/{id}/bonus with minutes=15 returns 200 with card HTML."""
    from unittest.mock import patch

    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.hostname = "host"
    mock_machine.ssh_port = 22
    mock_machine.ssh_user = "user"
    mock_machine.ssh_private_key = "key"
    mock_machine.friendly_name = "Gaming PC"
    mock_machine.child_id = "child1"
    mock_machine.daily_limit_mins = 60
    mock_machine.grace_period_mins = 5

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session(machine=mock_machine)
    try:
        client = TestClient(app)
        with patch(
            "familylink_server.routers.linux_machines.unlock_session", AsyncMock()
        ):
            resp = client.post(
                "/linux-machines/1/bonus",
                data={"minutes": "15"},
                cookies={"fl_session": _cookie()},
            )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert "Gaming PC" in resp.text


def test_bonus_on_locked_machine_calls_unlock():
    """POST /bonus on locked machine calls unlock_session and resets locked_at."""
    from unittest.mock import patch

    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.hostname = "host"
    mock_machine.ssh_port = 22
    mock_machine.ssh_user = "user"
    mock_machine.ssh_private_key = "key"
    mock_machine.friendly_name = "Gaming PC"
    mock_machine.child_id = "child1"
    mock_machine.daily_limit_mins = 60
    mock_machine.grace_period_mins = 5

    import datetime

    locked_snap = MagicMock()
    locked_snap.active_seconds = 3600
    locked_snap.bonus_mins = 0
    locked_snap.locked_at = datetime.datetime.now(datetime.UTC)
    locked_snap.poweroff_at = None
    locked_snap.updated_at = None

    mock_s = AsyncMock()
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = []
    mock_exec_result.scalar_one_or_none.return_value = locked_snap
    mock_s.execute = AsyncMock(return_value=mock_exec_result)
    mock_s.get = AsyncMock(return_value=mock_machine)
    mock_s.add = MagicMock()
    mock_s.flush = AsyncMock()
    mock_s.commit = AsyncMock()

    mock_unlock = AsyncMock()
    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: mock_s
    try:
        client = TestClient(app)
        with patch(
            "familylink_server.routers.linux_machines.unlock_session", mock_unlock
        ):
            resp = client.post(
                "/linux-machines/1/bonus",
                data={"minutes": "30"},
                cookies={"fl_session": _cookie()},
            )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    mock_unlock.assert_awaited_once()


def test_bonus_rejects_zero_minutes():
    """POST /bonus with minutes=0 returns 422 validation error."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session()
    try:
        client = TestClient(app)
        resp = client.post(
            "/linux-machines/1/bonus",
            data={"minutes": "0"},
            cookies={"fl_session": _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 422


def test_bonus_rejects_negative_minutes():
    """POST /bonus with minutes=-60 returns 422 validation error."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session()
    try:
        client = TestClient(app)
        resp = client.post(
            "/linux-machines/1/bonus",
            data={"minutes": "-60"},
            cookies={"fl_session": _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 422


def test_bonus_rejects_excessive_minutes():
    """POST /bonus with minutes=999 returns 422 validation error."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: _mock_svc()
    app.dependency_overrides[get_session] = lambda: _mock_session()
    try:
        client = TestClient(app)
        resp = client.post(
            "/linux-machines/1/bonus",
            data={"minutes": "999"},
            cookies={"fl_session": _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 422
