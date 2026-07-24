"""Shared fixtures for server tests."""

import os

import pytest

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://localhost/familylink_test')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-32-bytes-exactly!')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'test-client-id')
os.environ.setdefault('GOOGLE_CLIENT_SECRET', 'test-client-secret')
os.environ.setdefault('FAMILYLINK_GOOGLE_EMAIL', 'parent@gmail.com')
os.environ.setdefault('FAMILYLINK_COOKIES_B64', 'dGVzdA==')


@pytest.fixture(autouse=True)
def _reset_auto_refresh_backoff():
    """Prevent auto-refresh backoff state from leaking between tests.

    `_try_auto_refresh`'s backoff cooldown is process-global (module-level),
    so a failure in one test can suppress the sidecar call a later,
    unrelated test expects to make. Reset it before and after every test.
    """
    import familylink_server.main as main

    main._reset_refresh_backoff()
    yield
    main._reset_refresh_backoff()
