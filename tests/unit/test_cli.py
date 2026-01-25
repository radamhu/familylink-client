"""Unit tests for CLI module."""

from unittest.mock import patch

import pytest

from familylink.cli import (
    _get_expected_limits,
    _load_config,
    _parse_days,
    _parse_duration,
)


class TestParseDuration:
    """Test duration parsing."""

    def test_parse_duration_hours_and_minutes(self):
        """Test parsing H:MM format."""
        assert _parse_duration("1:30") == 90
        assert _parse_duration("0:10") == 10
        assert _parse_duration("2:00") == 120

    def test_parse_duration_empty(self):
        """Test parsing empty duration."""
        assert _parse_duration("") == 0

    def test_parse_duration_zero(self):
        """Test parsing zero duration."""
        assert _parse_duration("0:00") == 0


class TestParseDays:
    """Test day range parsing."""

    def test_parse_days_single(self):
        """Test parsing single day."""
        assert _parse_days("Mon") == ["monday"]
        assert _parse_days("Fri") == ["friday"]

    def test_parse_days_range(self):
        """Test parsing day range."""
        result = _parse_days("Mon-Fri")
        assert result == ["monday", "tuesday", "wednesday", "thursday", "friday"]

    def test_parse_days_weekend(self):
        """Test parsing weekend range."""
        result = _parse_days("Sat-Sun")
        assert result == ["saturday", "sunday"]

    def test_parse_days_empty(self):
        """Test parsing empty days string."""
        assert _parse_days("") == []

    def test_parse_days_case_insensitive(self):
        """Test that parsing is case insensitive."""
        assert _parse_days("MON") == ["monday"]
        assert _parse_days("mon") == ["monday"]


class TestLoadConfig:
    """Test config loading."""

    def test_load_config_valid_csv(self, sample_config_csv):
        """Test loading a valid config CSV."""
        config = _load_config(str(sample_config_csv))

        # Calculator should be always allowed
        assert config["Calculator"] == {"always_allowed": True}

        # YouTube should have limits
        assert "YouTube" in config
        assert "schedules" in config["YouTube"]
        assert "limits" in config["YouTube"]

    def test_load_config_with_time_ranges(self, tmp_path):
        """Test loading config with time ranges."""
        csv_path = tmp_path / "config.csv"
        csv_path.write_text(
            """App,Max Duration,Days,Time Ranges
Fortnite,1:00,Wed,13:00-18:00
"""
        )

        config = _load_config(str(csv_path))
        assert "Fortnite" in config
        assert "wednesday" in config["Fortnite"]["schedules"]
        assert config["Fortnite"]["schedules"]["wednesday"] == "13:00-18:00"
        assert config["Fortnite"]["limits"]["wednesday"] == 60

    def test_load_config_default_days(self, tmp_path):
        """Test loading config with default days (mon-sun)."""
        csv_path = tmp_path / "config.csv"
        csv_path.write_text(
            """App,Max Duration,Days,Time Ranges
Google Photos,0:10,,
"""
        )

        config = _load_config(str(csv_path))
        assert "Google Photos" in config
        # Should apply to all days
        days = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        for day in days:
            assert day in config["Google Photos"]["limits"]
            assert config["Google Photos"]["limits"][day] == 10


class TestGetExpectedLimits:
    """Test expected limits calculation."""

    @pytest.mark.freeze_time("2026-01-22 14:00:00")  # Wednesday
    def test_get_expected_limits_weekday(self):
        """Test expected limits on a weekday."""
        config = {
            "Calculator": {"always_allowed": True},
            "YouTube": {
                "schedules": {"wednesday": "00:00-23:59"},
                "limits": {"wednesday": 10},
            },
            "Spotify": {
                "schedules": {"wednesday": "13:00-18:00"},
                "limits": {"wednesday": 60},
            },
        }

        with patch("familylink.cli.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = lambda fmt: {
                "%A": "Wednesday",
                "%H:%M": "14:00",
            }.get(fmt)
            mock_dt.now.return_value.time.return_value.strftime.return_value = "14:00"

            expected = _get_expected_limits(config)

        assert expected["Calculator"] is True
        assert expected["YouTube"] == 10
        assert expected["Spotify"] == 60  # Within time range

    @pytest.mark.freeze_time("2026-01-25 09:00:00")  # Saturday
    def test_get_expected_limits_weekend(self):
        """Test expected limits on weekend."""
        config = {
            "YouTube": {
                "schedules": {"saturday": "00:00-23:59"},
                "limits": {"saturday": 30},
            },
        }

        with patch("familylink.cli.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = lambda fmt: {
                "%A": "Saturday",
                "%H:%M": "09:00",
            }.get(fmt)
            mock_dt.now.return_value.time.return_value.strftime.return_value = "09:00"

            expected = _get_expected_limits(config)

        assert expected["YouTube"] == 30


class TestCLIMain:
    """Test CLI main function."""

    def test_cli_help_message(self):
        """Test that CLI can display help message."""
        from familylink.cli import main

        with pytest.raises(SystemExit):
            with patch("sys.argv", ["familylink", "--help"]):
                main()
