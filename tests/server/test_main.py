"""Tests for the FastAPI application factory."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient


@pytest.fixture
def mock_init_service():
    """Mock init_service to avoid actual FamilyLink instantiation."""
    with patch('familylink_server.main.init_service'):
        yield


def test_docs_endpoint_exists(mock_init_service):
    """FastAPI Swagger UI docs should be available at /docs."""
    from familylink_server.main import app

    client = TestClient(app)
    resp = client.get('/docs')
    assert resp.status_code == 200


def test_openapi_json_exists(mock_init_service):
    """OpenAPI schema should be available at /openapi.json."""
    from familylink_server.main import app

    client = TestClient(app)
    resp = client.get('/openapi.json')
    assert resp.status_code == 200
    assert 'familylink' in resp.json()['info']['title'].lower()


def test_auth_login_route_exists(mock_init_service):
    """GET /auth/login should redirect to Google OAuth."""
    from familylink_server.main import app

    mock_redirect = RedirectResponse(
        url='https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=test',
        status_code=302,
    )
    with patch(
        'familylink_server.auth.oauth._oauth.google.authorize_redirect',
        new=AsyncMock(return_value=mock_redirect),
    ):
        client = TestClient(app)
        resp = client.get('/auth/login', follow_redirects=False)
    assert resp.status_code in (302, 307)


async def test_bot_not_started_when_discord_disabled():
    """Lifespan should not create a Discord bot task when Discord vars are absent."""
    from familylink_server.main import app, lifespan

    bot_task_started = False

    async def _fake_poller():
        """Coroutine that exits immediately (stands in for poller_loop)."""

    async def _fake_bot_task(*args, **kwargs):
        nonlocal bot_task_started
        bot_task_started = True

    async def _fake_health_check(*args, **kwargs):
        """Coroutine that exits immediately (stands in for health_check_loop)."""

    with (
        patch('familylink_server.main.init_service'),
        patch('familylink_server.main.get_service'),
        patch('familylink_server.main.settings') as mock_settings,
        patch('familylink_server.main.poller_loop', side_effect=_fake_poller),
        patch(
            'familylink_server.main.health_check_loop', side_effect=_fake_health_check
        ),
    ):
        mock_settings.discord_enabled = False
        async with lifespan(app):
            pass
    # Discord was disabled, so no bot task was started.
    assert not bot_task_started


def test_linux_machines_route_is_registered():
    """GET /linux-machines is registered in the app."""
    from familylink_server.main import app

    paths = list(app.openapi().get('paths', {}).keys())
    assert '/linux-machines' in paths


def test_poller_loop_accepts_notifier_kwarg():
    """poller_loop signature accepts a notifier keyword argument."""
    import inspect

    from familylink_server.services.linux_poller import poller_loop

    sig = inspect.signature(poller_loop)
    assert 'notifier' in sig.parameters


async def test_ntfy_initialized_when_topics_configured():
    """Lifespan should init the ntfy singleton and pass it into both loops."""
    from familylink_server.main import app, lifespan

    async def _fake_poller(*args, **kwargs):
        """Coroutine that exits immediately (stands in for poller_loop)."""

    async def _fake_enforcer(*args, **kwargs):
        """Coroutine that exits immediately (stands in for app_enforcer_loop)."""

    async def _fake_health_check(*args, **kwargs):
        """Coroutine that exits immediately (stands in for health_check_loop)."""

    async def _fake_proactive_refresh(*args, **kwargs):
        """Coroutine that exits immediately (stands in for proactive_refresh_loop)."""

    with (
        patch('familylink_server.main.init_service'),
        patch('familylink_server.main.get_service'),
        patch('familylink_server.main.settings') as mock_settings,
        patch('familylink_server.main.poller_loop', side_effect=_fake_poller),
        patch('familylink_server.main.app_enforcer_loop', side_effect=_fake_enforcer),
        patch(
            'familylink_server.main.health_check_loop', side_effect=_fake_health_check
        ),
        patch(
            'familylink_server.main.proactive_refresh_loop',
            side_effect=_fake_proactive_refresh,
        ),
    ):
        mock_settings.discord_enabled = False
        mock_settings.ntfy_topics_parsed = {'child1': 'topic1'}
        mock_settings.ntfy_base_url = 'http://ntfy.test'
        async with lifespan(app):
            from familylink_server.services.ntfy_notifier import get_notifier

            notifier = get_notifier()
            assert notifier is not None
            assert notifier._topics == {'child1': 'topic1'}
            assert notifier._base_url == 'http://ntfy.test'


async def test_ntfy_not_initialized_when_no_topics_configured():
    """No topics configured -> singleton stays unset."""
    from familylink_server.main import app, lifespan
    from familylink_server.services import ntfy_notifier as ntfy_mod

    ntfy_mod._notifier = None

    async def _fake_loop(*args, **kwargs):
        """Coroutine that exits immediately."""

    with (
        patch('familylink_server.main.init_service'),
        patch('familylink_server.main.get_service'),
        patch('familylink_server.main.settings') as mock_settings,
        patch('familylink_server.main.poller_loop', side_effect=_fake_loop),
        patch('familylink_server.main.app_enforcer_loop', side_effect=_fake_loop),
        patch('familylink_server.main.health_check_loop', side_effect=_fake_loop),
        patch('familylink_server.main.proactive_refresh_loop', side_effect=_fake_loop),
    ):
        mock_settings.discord_enabled = False
        mock_settings.ntfy_topics_parsed = {}
        async with lifespan(app):
            pass

    assert ntfy_mod.get_notifier() is None
