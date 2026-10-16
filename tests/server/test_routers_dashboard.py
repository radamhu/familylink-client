"""Tests for the dashboard (/) and history (/history) routers."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from freezegun import freeze_time
from itsdangerous import URLSafeSerializer

from familylink_server.config import settings
from familylink_server.db import get_session


def _cookie():
    s = URLSafeSerializer(settings.secret_key, salt='fl-session')
    return s.dumps({'email': settings.familylink_google_email})


def _fake_session(machines=None):
    """Return an async generator yielding a mock session."""
    machines = machines or []

    async def _gen():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = machines
        mock_result.scalar_one_or_none.return_value = None
        no_homework = MagicMock()
        no_homework.scalars.return_value.all.return_value = []

        async def _execute(stmt):
            return no_homework if 'homework_entries' in str(stmt) else mock_result

        mock_session.execute = AsyncMock(side_effect=_execute)
        yield mock_session

    return _gen


def test_dashboard_returns_200():
    """GET / with a valid session and no children returns 200 with 'Family Link'."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))
    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Family Link' in resp.text


def test_dashboard_strips_render_child_with_linux_machine():
    """Dashboard renders strip for child with a Linux machine; machine name is not in collapsed view."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_machine = MagicMock()
    mock_machine.id = 1
    mock_machine.child_id = 'child1'
    mock_machine.friendly_name = 'Gaming PC'
    mock_machine.daily_limit_mins = 60
    mock_machine.enabled = True

    child = MagicMock()
    child.user_id = 'child1'
    child.profile.display_name = 'Alice'
    child.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session(machines=[mock_machine])
    try:
        client = TestClient(app)
        resp = client.get('/', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'id="child-child1"' in resp.text
    assert (
        'Gaming PC' not in resp.text
    )  # detail is in expanded view, not collapsed strip


def test_history_returns_200():
    """GET /history with a valid session returns 200."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/history', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200


def test_dashboard_strips_show_child_name_and_color():
    """Dashboard renders a strip per child with colored avatar and name."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child = MagicMock()
    child.user_id = 'child1'
    child.profile.display_name = 'Alice'
    child.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Alice' in resp.text
    assert 'id="child-child1"' in resp.text
    assert '#a855f7' in resp.text  # first child gets purple
    assert 'hx-get="/children/child1/detail"' in resp.text


def test_child_detail_returns_expanded_view():
    """GET /children/{child_id}/detail returns the expanded partial with child name and top apps."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child = MagicMock()
    child.user_id = 'child1'
    child.profile.display_name = 'Alice'
    child.member_supervision_info.is_supervised_member = True

    session_mock = MagicMock()
    session_mock.app_id.android_app_package_name = 'com.example'
    today = __import__('datetime').date.today()
    session_mock.date = today
    session_mock.usage = '1800'

    app_mock = MagicMock()
    app_mock.package_name = 'com.example'
    app_mock.title = 'Example App'

    usage = MagicMock()
    usage.app_usage_sessions = [session_mock]
    usage.apps = [app_mock]
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/children/child1/detail', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Alice' in resp.text
    assert 'Example App' in resp.text
    assert 'hx-get="/children/child1/collapse"' in resp.text


def test_child_detail_returns_404_for_unknown_child():
    """GET /children/{child_id}/detail returns 404 when child_id not found."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))
    mock_svc.auth_failed = False

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/children/nobody/detail', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 404


def test_child_collapse_returns_strip():
    """GET /children/{child_id}/collapse returns the collapsed strip partial."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child = MagicMock()
    child.user_id = 'child1'
    child.profile.display_name = 'Alice'
    child.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get(
            '/children/child1/collapse', cookies={'fl_session': _cookie()}
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Alice' in resp.text
    assert 'hx-get="/children/child1/detail"' in resp.text
    assert '▶' in resp.text


def _hw(subject, registered_on, deadline, description='', seen=None):
    row = MagicMock()
    row.subject = subject
    row.description = description
    row.deadline = deadline
    row.registered_on = registered_on
    row.date = seen or registered_on
    return row


def _child_detail_html(homework_rows):
    """GET the expanded child card with the given homework rows in the DB."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child = MagicMock()
    child.user_id = 'child1'
    child.profile.display_name = 'Alice'
    child.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    async def _gen():
        mock_session = AsyncMock()
        no_machines = MagicMock()
        no_machines.scalars.return_value.all.return_value = []
        with_homework = MagicMock()
        with_homework.scalars.return_value.all.return_value = homework_rows
        mock_session.execute = AsyncMock(side_effect=[no_machines, with_homework])
        yield mock_session

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _gen
    try:
        client = TestClient(app)
        resp = client.get('/children/child1/detail', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    return resp.text


@freeze_time('2026-10-16')  # Friday
def test_child_detail_renders_week_table_with_today_column():
    html = _child_detail_html(
        [
            _hw(
                'Matek',
                date(2026, 10, 14),
                date(2026, 10, 16),
                'Oldd meg a 12. feladatot.',
            )
        ]
    )
    assert 'Matek' in html
    assert 'Oldd meg a 12. feladatot.' in html
    assert 'Weekend' in html
    assert 'class="hw-col hw-today' in html


@freeze_time('2026-10-16')
def test_child_detail_dims_passed_deadline():
    html = _child_detail_html([_hw('Magyar', date(2026, 10, 13), date(2026, 10, 15))])
    assert 'class="hw-item hw-past' in html


@freeze_time('2026-10-16')
def test_child_detail_empty_today_column_not_hidden_on_narrow():
    html = _child_detail_html([_hw('Magyar', date(2026, 10, 13), date(2026, 10, 15))])
    assert 'class="hw-col hw-today"' in html  # today is empty but never hw-empty


@freeze_time('2026-10-17')  # Saturday
def test_child_detail_saturday_highlights_weekend_with_today_label():
    html = _child_detail_html([_hw('Magyar', date(2026, 10, 13), date(2026, 10, 15))])
    assert 'class="hw-col hw-today hw-weekend' in html
    assert '· today' in html


@freeze_time('2026-10-16')
def test_child_detail_weekend_copy_for_later_week_deadline():
    html = _child_detail_html([_hw('Tori', date(2026, 10, 15), date(2026, 10, 19))])
    assert html.count('Tori') == 2  # Thursday original + Weekend copy
    assert '2026-10-19' in html


def test_child_detail_hides_homework_section_when_none_upcoming():
    """No 'Homework due' section when the DB query returns nothing (e.g. all expired)."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child = MagicMock()
    child.user_id = 'child1'
    child.profile.display_name = 'Alice'
    child.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    async def _gen():
        mock_session = AsyncMock()
        no_machines = MagicMock()
        no_machines.scalars.return_value.all.return_value = []
        no_homework = MagicMock()
        no_homework.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[no_machines, no_homework])
        yield mock_session

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _gen
    try:
        client = TestClient(app)
        resp = client.get('/children/child1/detail', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Homework due' not in resp.text
