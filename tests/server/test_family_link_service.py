"""Tests for FamilyLinkService singleton with async wrapper and cache-aside."""

from unittest.mock import MagicMock

import pytest

from familylink_server.services.family_link import FamilyLinkService


@pytest.fixture
def mock_client():
    """Return a MagicMock that mimics the FamilyLink client."""
    client = MagicMock()
    client.get_members.return_value = MagicMock(members=[])
    client.get_apps_and_usage.return_value = MagicMock(
        apps=[], device_info=[], app_usage_sessions=[]
    )
    client.lock_device.return_value = {}
    client.unlock_device.return_value = {}
    return client


@pytest.fixture
def service(mock_client):
    """Return a FamilyLinkService bypassing __init__, with TTL=0 (no caching)."""
    svc = FamilyLinkService.__new__(FamilyLinkService)
    svc._client = mock_client
    svc._ttl = 0  # disable caching for tests
    return svc


async def test_get_members_delegates_to_client(service, mock_client):
    """get_members should call the client and return its result."""
    result = await service.get_members()
    mock_client.get_members.assert_called_once()
    assert result.members == []


async def test_get_apps_and_usage_delegates_to_client(service, mock_client):
    """get_apps_and_usage should forward child_id to the client."""
    await service.get_apps_and_usage('child1')
    mock_client.get_apps_and_usage.assert_called_once_with('child1')


async def test_lock_device_delegates_to_client(service, mock_client):
    """lock_device should call the client with the correct keyword arguments."""
    await service.lock_device('dev1', child_id='child1')
    mock_client.lock_device.assert_called_once_with(
        device_id='dev1', account_id='child1'
    )


async def test_unlock_device_delegates_to_client(service, mock_client):
    """unlock_device should call the client with the correct keyword arguments."""
    await service.unlock_device('dev1', child_id='child1')
    mock_client.unlock_device.assert_called_once_with(
        device_id='dev1', account_id='child1'
    )


async def test_get_apps_and_usage_bypass_cache_ignores_fresh_cache(mock_client):
    """bypass_cache=True calls the client even when a fresh cache entry exists."""
    svc = FamilyLinkService.__new__(FamilyLinkService)
    svc._client = mock_client
    svc._ttl = 900
    svc._usage_cache = {}

    await svc.get_apps_and_usage('child1')
    await svc.get_apps_and_usage('child1', bypass_cache=True)

    assert mock_client.get_apps_and_usage.call_count == 2


def test_reinit_with_sapisid_sets_env_and_rebuilds_client(monkeypatch):
    """reinit_with_sapisid sets FAMILYLINK_SAPISID, clears cookies_b64, rebuilds client."""
    monkeypatch.setenv('FAMILYLINK_COOKIES_B64', 'stale-value')
    monkeypatch.delenv('FAMILYLINK_SAPISID', raising=False)

    svc = FamilyLinkService.__new__(FamilyLinkService)
    svc._members_cache = ('stale', None)
    svc._usage_cache = {'child1': ('stale', None)}

    svc.reinit_with_sapisid('fresh-sapisid-value')

    import os

    assert os.environ['FAMILYLINK_SAPISID'] == 'fresh-sapisid-value'
    assert 'FAMILYLINK_COOKIES_B64' not in os.environ
    assert svc._members_cache is None
    assert svc._usage_cache == {}
    assert svc._client is not None
