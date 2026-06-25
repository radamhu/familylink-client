"""Unit tests for Coolify push helper in familylink.cli."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from familylink.cli import _cmd_export_cookies, _push_to_coolify


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


def test_coolify_requires_base64():
    """--coolify without --base64 must exit 1 before touching browser."""
    with pytest.raises(SystemExit) as exc:
        _cmd_export_cookies(["--coolify"])
    assert exc.value.code == 1


def test_restart_requires_coolify():
    """--restart without --coolify must exit 1 before touching browser."""
    with pytest.raises(SystemExit) as exc:
        _cmd_export_cookies(["--restart"])
    assert exc.value.code == 1


def test_coolify_exits_on_missing_coolify_url(monkeypatch):
    """--coolify exits 1 when COOLIFY_URL is absent, before touching browser."""
    monkeypatch.delenv("COOLIFY_URL", raising=False)
    monkeypatch.setenv("COOLIFY_TOKEN", "tok")
    monkeypatch.setenv("COOLIFY_APP_UUID", "uuid")
    with pytest.raises(SystemExit) as exc:
        _cmd_export_cookies(["--base64", "--coolify"])
    assert exc.value.code == 1


def test_coolify_exits_on_missing_coolify_token(monkeypatch):
    """--coolify exits 1 when COOLIFY_TOKEN is absent, before touching browser."""
    monkeypatch.setenv("COOLIFY_URL", "http://coolify:8000")
    monkeypatch.delenv("COOLIFY_TOKEN", raising=False)
    monkeypatch.setenv("COOLIFY_APP_UUID", "uuid")
    with pytest.raises(SystemExit) as exc:
        _cmd_export_cookies(["--base64", "--coolify"])
    assert exc.value.code == 1


def test_coolify_exits_on_missing_coolify_app_uuid(monkeypatch):
    """--coolify exits 1 when COOLIFY_APP_UUID is absent, before touching browser."""
    monkeypatch.setenv("COOLIFY_URL", "http://coolify:8000")
    monkeypatch.setenv("COOLIFY_TOKEN", "tok")
    monkeypatch.delenv("COOLIFY_APP_UUID", raising=False)
    with pytest.raises(SystemExit) as exc:
        _cmd_export_cookies(["--base64", "--coolify"])
    assert exc.value.code == 1
