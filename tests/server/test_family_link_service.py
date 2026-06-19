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
    await service.get_apps_and_usage("child1")
    mock_client.get_apps_and_usage.assert_called_once_with("child1")


async def test_lock_device_delegates_to_client(service, mock_client):
    """lock_device should call the client with the correct keyword arguments."""
    await service.lock_device("dev1", child_id="child1")
    mock_client.lock_device.assert_called_once_with(
        device_id="dev1", account_id="child1"
    )


async def test_unlock_device_delegates_to_client(service, mock_client):
    """unlock_device should call the client with the correct keyword arguments."""
    await service.unlock_device("dev1", child_id="child1")
    mock_client.unlock_device.assert_called_once_with(
        device_id="dev1", account_id="child1"
    )
