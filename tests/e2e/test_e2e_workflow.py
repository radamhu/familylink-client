"""End-to-end workflow tests with mocked API."""

from unittest.mock import patch

import pytest

from familylink import FamilyLink
from familylink.cli import _apply_config, _load_config
from familylink.models import AppUsage


class TestE2EWorkflow:
    """Test complete workflows from start to finish."""

    def test_full_csv_to_api_workflow(
        self,
        sample_config_csv,
        mock_env_vars,
        mock_members_response,
        mock_apps_response,
        httpx_mock,
    ):
        """Test complete workflow: Load CSV → Parse → Apply limits."""
        # Mock API responses
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/families/mine/members",
            json=mock_members_response,
        )
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/people/child_456/appsandusage",
            json=mock_apps_response,
        )

        # Load config
        config = _load_config(str(sample_config_csv))
        assert "Calculator" in config
        assert "YouTube" in config

        # Create client
        client = FamilyLink(account_id="child_456")

        # Get apps (dry run)
        apps_data = client.get_apps_and_usage("child_456")
        assert "apps" in apps_data

    def test_member_discovery_workflow(
        self, mock_env_vars, mock_members_response, httpx_mock
    ):
        """Test workflow: Create client → Get members → Identify child."""
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/families/mine/members",
            json=mock_members_response,
        )

        # Create client without account_id
        client = FamilyLink()

        # Get members
        members = client.get_members()
        assert len(members.members) == 2

        # Find child
        child = next(m for m in members.members if m.role == "child")
        assert child.user_id == "child_456"
        assert child.profile.display_name == "Kid User"

    def test_app_limit_workflow(self, mock_env_vars, mock_apps_response, httpx_mock):
        """Test workflow: Get apps → Check limits → Verify state."""
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/people/child_456/appsandusage",
            json=mock_apps_response,
        )

        client = FamilyLink(account_id="child_456")
        apps_data = client.get_apps_and_usage("child_456")
        usage = AppUsage(**apps_data)

        # Verify Spotify has 30 min limit
        spotify = next(a for a in usage.apps if a.title == "Spotify")
        assert spotify.supervision_setting.usage_limit.daily_usage_limit_mins == 30

        # Verify YouTube is blocked
        youtube = next(a for a in usage.apps if a.title == "YouTube")
        assert youtube.supervision_setting.hidden is True

        # Verify Calculator is always allowed
        calculator = next(a for a in usage.apps if a.title == "Calculator")
        assert calculator.supervision_setting.always_allowed_app_info is not None

    def test_csv_config_workflow_dry_run(
        self, sample_config_csv, mock_env_vars, mock_apps_response, httpx_mock
    ):
        """Test full CSV workflow in dry-run mode."""
        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/people/child_456/appsandusage",
            json=mock_apps_response,
        )

        config = _load_config(str(sample_config_csv))
        client = FamilyLink(account_id="child_456")

        # Apply in dry-run mode (should not raise errors)
        with patch("familylink.cli.console"):
            _apply_config(client, config, dry_run=True)


class TestE2EErrorHandling:
    """Test error handling in E2E scenarios."""

    def test_missing_config_file_handling(self, tmp_path):
        """Test handling of missing config file."""
        non_existent = tmp_path / "does_not_exist.csv"

        with pytest.raises(FileNotFoundError):
            _load_config(str(non_existent))

    def test_invalid_sapisid_handling(self, monkeypatch):
        """Test handling of invalid SAPISID."""
        monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)

        with patch("familylink.client.browser_cookie3", None):
            with pytest.raises(ValueError, match="Could not find SAPISID"):
                FamilyLink()

    def test_network_error_handling(self, mock_env_vars, httpx_mock):
        """Test handling of network errors."""
        import httpx

        httpx_mock.add_response(
            url="https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/families/mine/members",
            status_code=500,
        )

        client = FamilyLink()
        with pytest.raises(httpx.HTTPStatusError):
            client.get_members()
