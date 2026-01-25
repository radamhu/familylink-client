"""Integration tests for CLI functionality."""

import csv
from unittest.mock import MagicMock, patch

from familylink.cli import _apply_config, _create_default_config, _load_config


class TestCLIConfigIntegration:
    """Test CLI config loading and application."""

    def test_load_and_parse_full_config(self, sample_config_csv):
        """Test loading a complete config file."""
        config = _load_config(str(sample_config_csv))

        # Verify all apps are loaded
        assert "Calculator" in config
        assert "YouTube" in config
        assert "Spotify" in config
        assert "Google Photos" in config

        # Verify Calculator is always allowed
        assert config["Calculator"] == {"always_allowed": True}

        # Verify YouTube has different limits for weekdays/weekends
        assert config["YouTube"]["limits"]["monday"] == 10
        assert config["YouTube"]["limits"]["saturday"] == 30

    def test_create_default_config(self, tmp_path, mock_env_vars, mock_apps_response):
        """Test creating default config from current apps."""
        config_path = tmp_path / "default_config.csv"

        with patch("familylink.FamilyLink") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            from familylink.models import AppUsage

            mock_client.get_apps_and_usage.return_value = AppUsage(**mock_apps_response)

            _create_default_config(mock_client, str(config_path))

        # Verify file was created
        assert config_path.exists()

        # Verify CSV structure
        with open(config_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 3  # 3 apps in mock
            assert rows[0]["App"] == "Calculator"
            assert rows[0]["Max Duration"] == "0:00"

    def test_apply_config_integration(
        self, sample_config_csv, mock_env_vars, mock_apps_response
    ):
        """Test applying config to client."""
        config = _load_config(str(sample_config_csv))

        with patch("familylink.FamilyLink") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            from familylink.models import AppUsage

            mock_client.get_apps_and_usage.return_value = AppUsage(**mock_apps_response)

            # Run apply_config in dry-run mode
            _apply_config(mock_client, config, dry_run=True)

            # Verify get_apps_and_usage was called
            mock_client.get_apps_and_usage.assert_called_once()
