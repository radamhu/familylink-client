"""Unit tests for Coolify push helper in familylink.cli."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from familylink.cli import _push_to_coolify


def _resp(is_success=True, status_code=200, text="ok"):
    r = MagicMock()
    r.is_success = is_success
    r.status_code = status_code
    r.text = text
    return r


@patch("familylink.cli.httpx")
def test_push_patches_env_var(mock_httpx):
    """PATCH is called with the correct URL, headers, and JSON body."""
    mock_httpx.patch.return_value = _resp()
    _push_to_coolify("b64val", "http://coolify:8000", "tok", "app-uuid", restart=False)
    mock_httpx.patch.assert_called_once_with(
        "http://coolify:8000/api/v1/applications/app-uuid/envs",
        headers={"Authorization": "Bearer tok"},
        json={"key": "FAMILYLINK_COOKIES_B64", "value": "b64val", "is_preview": False},
    )
    mock_httpx.get.assert_not_called()


@patch("familylink.cli.httpx")
def test_push_does_not_restart_by_default(mock_httpx):
    """No restart GET request is made when restart=False."""
    mock_httpx.patch.return_value = _resp()
    _push_to_coolify("b64val", "http://coolify:8000", "tok", "app-uuid", restart=False)
    mock_httpx.get.assert_not_called()


@patch("familylink.cli.httpx")
def test_push_restarts_when_requested(mock_httpx):
    """Restart GET is called with correct URL when restart=True."""
    mock_httpx.patch.return_value = _resp()
    mock_httpx.get.return_value = _resp()
    _push_to_coolify("b64val", "http://coolify:8000", "tok", "app-uuid", restart=True)
    mock_httpx.get.assert_called_once_with(
        "http://coolify:8000/api/v1/applications/app-uuid/restart",
        headers={"Authorization": "Bearer tok"},
    )


@patch("familylink.cli.httpx")
def test_push_exits_on_patch_api_error(mock_httpx):
    """sys.exit(1) is called when the PATCH response is not successful."""
    mock_httpx.patch.return_value = _resp(
        is_success=False, status_code=401, text="Unauthorized"
    )
    with pytest.raises(SystemExit) as exc:
        _push_to_coolify(
            "b64val", "http://coolify:8000", "tok", "app-uuid", restart=False
        )
    assert exc.value.code == 1


@patch("familylink.cli.httpx")
def test_push_exits_on_restart_api_error(mock_httpx):
    """sys.exit(1) is called when the restart GET response is not successful."""
    mock_httpx.patch.return_value = _resp()
    mock_httpx.get.return_value = _resp(
        is_success=False, status_code=500, text="Server Error"
    )
    with pytest.raises(SystemExit) as exc:
        _push_to_coolify(
            "b64val", "http://coolify:8000", "tok", "app-uuid", restart=True
        )
    assert exc.value.code == 1


@patch("familylink.cli.httpx")
def test_push_exits_on_patch_network_error(mock_httpx):
    """sys.exit(1) is called when the PATCH raises a network error."""
    mock_httpx.patch.side_effect = httpx.RequestError("Connection refused")
    mock_httpx.RequestError = httpx.RequestError
    with pytest.raises(SystemExit) as exc:
        _push_to_coolify(
            "b64val", "http://coolify:8000", "tok", "app-uuid", restart=False
        )
    assert exc.value.code == 1


@patch("familylink.cli.httpx")
def test_push_exits_on_restart_network_error(mock_httpx):
    """sys.exit(1) is called when the restart GET raises a network error."""
    mock_httpx.patch.return_value = _resp()
    mock_httpx.get.side_effect = httpx.RequestError("Connection refused")
    mock_httpx.RequestError = httpx.RequestError
    with pytest.raises(SystemExit) as exc:
        _push_to_coolify(
            "b64val", "http://coolify:8000", "tok", "app-uuid", restart=True
        )
    assert exc.value.code == 1
