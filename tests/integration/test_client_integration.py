"""Integration tests for FamilyLink client with various auth methods."""

import pytest

from familylink import FamilyLink


class TestClientAuthIntegration:
    """Test client initialization with different auth methods."""

    def test_init_with_env_variable(self, mock_env_vars):
        """Test client initialization with FAMILYLINK_SAPISID env var."""
        client = FamilyLink()
        assert client._session is not None
        assert client._headers["Authorization"].startswith("SAPISIDHASH ")

    def test_init_with_cookie_file_path(self, mock_cookies_file, monkeypatch):
        """Test client initialization with cookie file path."""
        monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
        monkeypatch.setenv("FAMILYLINK_BROWSER", "txt")

        client = FamilyLink(cookie_file_path=mock_cookies_file)
        assert client._session is not None

    def test_init_with_browser_txt_mode(self, mock_cookies_file, monkeypatch):
        """Test client initialization with browser='txt' mode."""
        monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
        monkeypatch.setenv("FAMILYLINK_COOKIE_FILE", str(mock_cookies_file))

        client = FamilyLink(browser="txt")
        assert client._session is not None

    def test_profile_directory_auth(self, tmp_path, monkeypatch):
        """Test auth from profile directory with sapisid.txt."""
        profile_dir = tmp_path / "profile_test"
        profile_dir.mkdir()
        sapisid_file = profile_dir / "sapisid.txt"
        sapisid_file.write_text("profile_sapisid_123")

        monkeypatch.setenv("FAMILYLINK_PROFILES_DIR", str(tmp_path))
        monkeypatch.chdir(profile_dir)

        client = FamilyLink()
        assert client._session is not None

    def test_authuser_from_file(self, tmp_path, monkeypatch):
        """Test loading authuser from authuser.txt in profile dir."""
        profile_dir = tmp_path / "profile_test"
        profile_dir.mkdir()

        sapisid_file = profile_dir / "sapisid.txt"
        sapisid_file.write_text("test_sapisid")

        authuser_file = profile_dir / "authuser.txt"
        authuser_file.write_text("2")

        monkeypatch.setenv("FAMILYLINK_PROFILES_DIR", str(tmp_path))
        monkeypatch.chdir(profile_dir)

        # Just verify it initializes without error
        client = FamilyLink()
        assert client._session is not None


class TestClientAPIIntegration:
    """Test client API methods integration."""

    @pytest.fixture
    def client(self, mock_env_vars):
        """Create client for testing."""
        return FamilyLink(account_id="child_456")

    def test_get_members_integration(self, client, httpx_mock, mock_members_response):
        """Test get_members returns proper MembersResponse object."""
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/families/mine/members",
            json=mock_members_response,
        )

        members = client.get_members()
        assert members.my_user_id == "parent_123"
        assert len(members.members) == 2
        assert members.members[1].profile.display_name == "Kid User"

    def test_get_apps_integration(self, client, httpx_mock, mock_apps_response):
        """Test get_apps_and_usage returns proper data structure."""
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/people/child_456/appsandusage",
            json=mock_apps_response,
        )

        apps = client.get_apps_and_usage("child_456")
        assert "apps" in apps
        assert len(apps["apps"]) == 3
        assert apps["apps"][0]["title"] == "Spotify"
