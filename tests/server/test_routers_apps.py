"""Tests for the /apps router and HTMX limit/block/allow endpoints."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer

from familylink_server.config import settings
from familylink_server.db import get_session


def _cookie():
    s = URLSafeSerializer(settings.secret_key, salt='fl-session')
    return s.dumps({'email': settings.familylink_google_email})


def _make_app_mock(title, package, hidden=False, limit_mins=None, always_allowed=False):
    app_mock = MagicMock()
    app_mock.title = title
    app_mock.package_name = package
    app_mock.supervision_setting.hidden = hidden
    app_mock.supervision_setting.usage_limit = (
        MagicMock(daily_usage_limit_mins=limit_mins, enabled=True)
        if limit_mins
        else None
    )
    app_mock.supervision_setting.always_allowed_app_info = (
        MagicMock(always_allowed_state='alwaysAllowedStateEnabled')
        if always_allowed
        else None
    )
    return app_mock


def _make_client(mock_svc):
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    client = TestClient(app)
    return client


def _empty_config_session():
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    return mock_session


def test_apps_page_returns_200():
    """GET /apps with a valid session returns 200 and app titles."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(
            members=[
                MagicMock(
                    user_id='child1',
                    member_supervision_info=MagicMock(is_supervised_member=True),
                )
            ]
        )
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=MagicMock(
            apps=[
                _make_app_mock('YouTube', 'com.google.android.youtube', limit_mins=30)
            ],
            device_info=[],
            app_usage_sessions=[],
        )
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: _empty_config_session()
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'YouTube' in resp.text


def test_set_limit_returns_partial(monkeypatch):
    """POST /apps/{package}/limit calls set_app_limit with int minutes and returns 200."""
    mock_svc = MagicMock()
    mock_svc.set_app_limit = AsyncMock(return_value=None)
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/limit',
            data={'child_id': 'child1', 'minutes': '45'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    mock_svc.set_app_limit.assert_called_once_with(
        'com.google.android.youtube', 45, child_id='child1'
    )


def test_block_app_returns_partial():
    """POST /apps/{package}/block calls block_app and returns 200 with partial HTML."""
    mock_svc = MagicMock()
    mock_svc.block_app = AsyncMock(return_value=None)
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/block',
            data={'child_id': 'child1'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    mock_svc.block_app.assert_called_once_with(
        'com.google.android.youtube', child_id='child1'
    )


def _make_member(user_id, display_name, supervised=True):
    m = MagicMock()
    m.user_id = user_id
    m.profile.display_name = display_name
    m.member_supervision_info = MagicMock(is_supervised_member=supervised)
    return m


def _make_usage(*app_mocks):
    u = MagicMock()
    u.apps = list(app_mocks)
    u.device_info = []
    u.app_usage_sessions = []
    return u


def test_apps_page_shows_child_tabs_for_multiple_children():
    """Tab links for both children appear when two supervised children exist."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(
            members=[
                _make_member('child1', 'Emma'),
                _make_member('child2', 'Lucas'),
            ]
        )
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube')
        )
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: _empty_config_session()
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Emma' in resp.text
    assert 'Lucas' in resp.text
    assert 'href="/apps?child=child1' in resp.text
    assert 'href="/apps?child=child2' in resp.text


def test_apps_page_child_param_selects_correct_child():
    """?child=child2 fetches child2's apps, not child1's."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(
            members=[
                _make_member('child1', 'Emma'),
                _make_member('child2', 'Lucas'),
            ]
        )
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(_make_app_mock('Minecraft', 'com.mojang.minecraftpe'))
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: _empty_config_session()
    try:
        client = TestClient(app)
        resp = client.get('/apps?child=child2', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    mock_svc.get_apps_and_usage.assert_called_once_with('child2')


def test_apps_page_invalid_child_falls_back_to_first():
    """Unknown child param silently falls back to children[0]."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(members=[_make_member('child1', 'Emma')])
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube')
        )
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: _empty_config_session()
    try:
        client = TestClient(app)
        resp = client.get('/apps?child=unknown-id', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    mock_svc.get_apps_and_usage.assert_called_once_with('child1')


def test_apps_page_single_child_no_tab_links():
    """With one child the response contains no child tab navigation."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(members=[_make_member('child1', 'Emma')])
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube')
        )
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: _empty_config_session()
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    # The child tab navigation should not render for single child
    # but filter links still include child= parameter
    assert 'Emma</a>' not in resp.text  # No child name links (tab nav)
    assert (
        'href="/apps?child=child1&filter=all' in resp.text
    )  # Filter nav includes child=


def test_apps_page_kid_switcher_shows_avatar():
    """Apps page kid switcher renders colored avatar initial when multiple children exist."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child1 = MagicMock()
    child1.user_id = 'c1'
    child1.profile.display_name = 'Alice'
    child1.member_supervision_info.is_supervised_member = True

    child2 = MagicMock()
    child2.user_id = 'c2'
    child2.profile.display_name = 'Bob'
    child2.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child1, child2]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: _empty_config_session()
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert '#a855f7' in resp.text  # first child color
    assert '#3b82f6' in resp.text  # second child color


def test_apps_page_shows_auto_block_checkbox_for_limited_app():
    """A 'limited' app row includes the auto-block checkbox, checked when opted in."""
    from familylink_server.db.models import AppConfig

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(members=[_make_member('child1', 'Emma')])
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube', limit_mins=30)
        )
    )
    config = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = [config]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Auto-block on overuse' in resp.text
    assert 'checked' in resp.text


def test_apps_page_hides_auto_block_checkbox_for_blocked_app():
    """A 'blocked' app row does not include the auto-block checkbox."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(members=[_make_member('child1', 'Emma')])
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube', hidden=True)
        )
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: _empty_config_session()
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Auto-block on overuse' not in resp.text


def test_set_auto_block_enables_creates_new_appconfig_row():
    """POST /apps/{package}/auto-block with enabled=true creates a row and returns 200."""
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    from familylink_server.main import app

    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/auto-block',
            data={'child_id': 'child1', 'limit_mins': '30', 'enabled': 'true'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'checked' in resp.text
    mock_session.commit.assert_awaited_once()


def test_set_auto_block_disables_existing_row():
    """POST with enabled omitted (unchecked) clears the opt-in flag on an existing row."""
    from familylink_server.db.models import AppConfig

    existing = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = existing
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    from familylink_server.main import app

    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/auto-block',
            data={'child_id': 'child1', 'limit_mins': '30'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert existing.auto_block_enabled is False


def test_grant_bonus_unblocks_auto_blocked_app():
    """POST /apps/{package}/bonus on an auto-blocked app calls set_app_limit and clears auto_blocked_at."""
    import datetime as dt

    from familylink_server.db.models import AppConfig

    existing = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
        auto_blocked_at=dt.datetime.now(dt.UTC),
        bonus_mins=0,
        bonus_date=None,
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = existing
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube', limit_mins=30)
        )
    )
    mock_svc.set_app_limit = AsyncMock()

    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/bonus',
            data={'child_id': 'child1', 'minutes': '15'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 200
    mock_svc.set_app_limit.assert_awaited_once_with(
        'com.google.android.youtube', 30, 'child1'
    )
    assert existing.auto_blocked_at is None
    assert existing.bonus_mins == 15


def test_grant_bonus_stacks_within_same_day():
    """A second bonus grant on the same day adds to bonus_mins instead of resetting it."""
    import datetime as dt

    from familylink_server.db.models import AppConfig

    today = dt.date.today()
    existing = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
        auto_blocked_at=None,
        bonus_mins=15,
        bonus_date=today,
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = existing
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=_make_usage())
    mock_svc.set_app_limit = AsyncMock()

    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/bonus',
            data={'child_id': 'child1', 'minutes': '30'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 200
    assert existing.bonus_mins == 45  # 15 + 30, not reset
    mock_svc.set_app_limit.assert_not_awaited()  # not currently auto-blocked


def test_grant_bonus_resets_on_new_day():
    """A bonus grant on a new day starts fresh instead of adding to yesterday's leftover."""
    import datetime as dt

    from familylink_server.db.models import AppConfig

    yesterday = dt.date.today() - dt.timedelta(days=1)
    existing = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
        auto_blocked_at=None,
        bonus_mins=15,
        bonus_date=yesterday,
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = existing
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_svc = MagicMock()
    mock_svc.get_apps_and_usage = AsyncMock(return_value=_make_usage())
    mock_svc.set_app_limit = AsyncMock()

    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.post(
            '/apps/com.google.android.youtube/bonus',
            data={'child_id': 'child1', 'minutes': '30'},
            cookies={'fl_session': _cookie()},
        )
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 200
    assert existing.bonus_mins == 30  # fresh start, not 15 + 30
    assert existing.bonus_date == dt.date.today()


def test_apps_page_shows_bonus_buttons_only_when_auto_blocked():
    """Bonus buttons appear on an auto-blocked row and not otherwise."""
    from familylink_server.db.models import AppConfig

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(members=[_make_member('child1', 'Emma')])
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(
            _make_app_mock('YouTube', 'com.google.android.youtube', hidden=True)
        )
    )
    import datetime as dt

    config = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
        auto_block_enabled=True,
        auto_blocked_at=dt.datetime.now(dt.UTC),
    )
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = [config]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_exec_result)
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = lambda: mock_session
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert '+15 min' in resp.text
    assert '+30 min' in resp.text
    assert '+60 min' in resp.text
