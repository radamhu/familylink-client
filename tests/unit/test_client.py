"""Unit tests for FamilyLink client."""

import hashlib
import time
from unittest.mock import patch

import httpx
import pytest

from familylink.client import FamilyLink, _generate_sapisidhash


class TestSapisidHash:
    """Test SAPISID hash generation."""

    def test_generate_sapisidhash_format(self):
        """Test that SAPISIDHASH has correct format."""
        sapisid = "test_sapisid_123"
        origin = "https://familylink.google.com"
        result = _generate_sapisidhash(sapisid, origin)

        # Should be "timestamp_hash"
        assert "_" in result
        parts = result.split("_")
        assert len(parts) == 2
        assert parts[0].isdigit()
        assert len(parts[1]) == 40  # SHA1 hex digest

    def test_generate_sapisidhash_consistency(self):
        """Test that same inputs produce valid hash (allowing time change)."""
        sapisid = "test_sapisid_123"
        origin = "https://familylink.google.com"

        hash1 = _generate_sapisidhash(sapisid, origin)
        time.sleep(0.001)  # Ensure time difference
        hash2 = _generate_sapisidhash(sapisid, origin)

        # Both should be valid format
        assert "_" in hash1
        assert "_" in hash2
        # Timestamps will differ slightly
        ts1 = int(hash1.split("_")[0])
        ts2 = int(hash2.split("_")[0])
        assert ts2 >= ts1

    def test_generate_sapisidhash_sha1_verification(self):
        """Test that the SHA1 hash is correctly generated."""
        sapisid = "test_sapisid"
        origin = "https://familylink.google.com"

        with patch("time.time", return_value=1234567.890):
            result = _generate_sapisidhash(sapisid, origin)
            timestamp_ms = int(1234567.890 * 1000)
            expected_msg = f"{timestamp_ms} {sapisid} {origin}"
            expected_hash = hashlib.sha1(expected_msg.encode()).hexdigest()
            assert result == f"{timestamp_ms}_{expected_hash}"


class TestFamilyLinkInit:
    """Test FamilyLink client initialization."""

    def test_init_with_env_sapisid(self, mock_env_vars):
        """Test initialization with FAMILYLINK_SAPISID env var."""
        client = FamilyLink()
        assert client._session is not None
        assert "Authorization" in client._headers
        assert client._headers["Authorization"].startswith("SAPISIDHASH ")

    def test_init_with_account_id(self, mock_env_vars):
        """Test initialization with explicit account_id."""
        client = FamilyLink(account_id="test_account_123")
        assert client.account_id == "test_account_123"

    def test_init_without_sapisid_raises_error(self, monkeypatch):
        """Test that missing SAPISID raises ValueError."""
        monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
        with patch("familylink.client.browser_cookie3", None):
            with pytest.raises(ValueError, match="Could not find SAPISID"):
                FamilyLink()

    def test_init_with_cookie_file(self, mock_cookies_file, monkeypatch):
        """Test initialization with cookie file."""
        monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
        monkeypatch.setenv("FAMILYLINK_COOKIE_FILE", str(mock_cookies_file))
        monkeypatch.setenv("FAMILYLINK_BROWSER", "txt")

        client = FamilyLink()
        assert client._session is not None
        assert "Authorization" in client._headers

    def test_init_headers_structure(self, mock_env_vars):
        """Test that headers are properly structured."""
        client = FamilyLink()
        assert client._headers["User-Agent"] == "Mozilla/5.0"
        assert client._headers["Origin"] == "https://familylink.google.com"
        assert client._headers["Content-Type"] == "application/json+protobuf"
        assert (
            client._headers["X-Goog-Api-Key"]
            == "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
        )


class TestFamilyLinkMethods:
    """Test FamilyLink client methods."""

    @pytest.fixture
    def client(self, mock_env_vars):
        """Create a FamilyLink client for testing."""
        return FamilyLink(account_id="child_456")

    def test_ensure_account_id_with_explicit_id(self, client):
        """Test _ensure_account_id when account_id is set."""
        assert client._ensure_account_id() == "child_456"

    def test_ensure_account_id_auto_detect(self, mock_env_vars, mock_members_response):
        """Test _ensure_account_id auto-detects child account."""
        client = FamilyLink()  # No account_id

        with patch.object(client, "get_members") as mock_get:
            from familylink.models import MembersResponse

            mock_get.return_value = MembersResponse(**mock_members_response)
            account_id = client._ensure_account_id()
            assert account_id == "child_456"  # Child account detected

    def test_get_members(self, client, httpx_mock, mock_members_response):
        """Test get_members API call."""
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/families/mine/members",
            method="GET",
            json=mock_members_response,
        )

        response = client.get_members()
        assert len(response.members) == 2
        assert response.my_user_id == "parent_123"
        assert response.members[1].user_id == "child_456"

    def test_get_apps_and_usage(self, client, httpx_mock, mock_apps_response):
        """Test get_apps_and_usage API call."""
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/people/child_456/appsandusage",
            method="GET",
            json=mock_apps_response,
        )

        response = client.get_apps_and_usage("child_456")
        assert "apps" in response
        assert len(response["apps"]) == 3

    def test_get_raises_on_http_error(self, client, httpx_mock):
        """Test that _get raises on HTTP errors."""
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/test",
            method="GET",
            status_code=403,
        )

        with pytest.raises(httpx.HTTPStatusError):
            client._get("/test")

    def test_post_method(self, client, httpx_mock):
        """Test _post method sends correct request."""
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/test",
            method="POST",
            json={"status": "ok"},
        )

        response = client._post("/test", '{"data": "test"}')
        assert response.status_code == 200


class TestFamilyLinkProfileAuth:
    """Test profile-based authentication."""

    def test_sapisid_from_file(self, tmp_path, monkeypatch):
        """Test loading SAPISID from sapisid.txt in profile dir."""
        # Setup profile directory
        profile_dir = tmp_path / "profile1"
        profile_dir.mkdir()
        sapisid_file = profile_dir / "sapisid.txt"
        sapisid_file.write_text("file_sapisid_value")

        # Set environment to simulate profile directory
        monkeypatch.setenv("FAMILYLINK_PROFILES_DIR", str(tmp_path))
        monkeypatch.chdir(profile_dir)

        client = FamilyLink()
        assert "Authorization" in client._headers
        assert "SAPISIDHASH" in client._headers["Authorization"]

    def test_cookies_from_file(self, tmp_path, monkeypatch):
        """Test loading cookies from cookies.txt in profile dir."""
        profile_dir = tmp_path / "profile1"
        profile_dir.mkdir()
        cookies_file = profile_dir / "cookies.txt"
        cookies_file.write_text(
            """# Netscape HTTP Cookie File
.google.com	TRUE	/	TRUE	0	SAPISID	cookie_sapisid_value
"""
        )

        monkeypatch.setenv("FAMILYLINK_PROFILES_DIR", str(tmp_path))
        monkeypatch.chdir(profile_dir)

        client = FamilyLink()
        assert "Authorization" in client._headers
