"""Pytest configuration and shared fixtures."""

from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def sample_sapisid() -> str:
    """Return a sample SAPISID value for testing."""
    return "test_sapisid_12345"


@pytest.fixture
def sample_cookie_jar(sample_sapisid: str) -> CookieJar:
    """Create a CookieJar with a sample SAPISID cookie."""
    jar = CookieJar()
    cookie = Cookie(
        version=0,
        name="SAPISID",
        value=sample_sapisid,
        port=None,
        port_specified=False,
        domain=".google.com",
        domain_specified=True,
        domain_initial_dot=True,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
    )
    jar.set_cookie(cookie)
    return jar


@pytest.fixture
def mock_members_response() -> dict[str, Any]:
    """Return mock members API response."""
    return {
        "members": [
            {
                "userId": "parent_123",
                "role": "parent",
                "profile": {
                    "displayName": "Parent User",
                    "profileImageUrl": "https://example.com/parent.jpg",
                    "email": "parent@example.com",
                    "familyName": "Smith",
                    "givenName": "John",
                    "standardGender": "male",
                    "defaultProfileImageUrl": "https://example.com/default.jpg",
                },
                "state": "active",
            },
            {
                "userId": "child_456",
                "role": "child",
                "profile": {
                    "displayName": "Kid User",
                    "profileImageUrl": "https://example.com/kid.jpg",
                    "email": "kid@example.com",
                    "familyName": "Smith",
                    "givenName": "Jane",
                    "standardGender": "female",
                    "birthday": {"day": 15, "month": 6, "year": 2015},
                    "defaultProfileImageUrl": "https://example.com/default.jpg",
                },
                "state": "active",
                "ageBandLabel": "child",
                "memberSupervisionInfo": {
                    "isSupervisedMember": True,
                    "isGuardianLinkedAccount": False,
                },
            },
        ],
        "apiHeader": {"serverTimestampMillis": "1234567890000"},
        "myUserId": "parent_123",
    }


@pytest.fixture
def mock_apps_response() -> dict[str, Any]:
    """Return mock apps and usage API response."""
    return {
        "apiHeader": {"serverTimestampMillis": "1234567890000"},
        "apps": [
            {
                "packageName": "com.spotify.music",
                "title": "Spotify",
                "iconUrl": "https://example.com/spotify.png",
                "supervisionSetting": {
                    "hidden": False,
                    "hiddenSetExplicitly": False,
                    "usageLimit": {"dailyUsageLimitMins": 30, "enabled": True},
                },
                "installTimeMillis": "1234567890000",
                "enforcedEnabledStatus": "enabled",
                "appSource": "googlePlay",
                "supervisionCapabilities": [
                    "capabilityAlwaysAllowApp",
                    "capabilityBlock",
                    "capabilityUsageLimit",
                ],
                "adSupportStatus": "adsSupported",
                "iapSupportStatus": "iapSupported",
                "deviceIds": ["device_1"],
            },
            {
                "packageName": "com.google.android.youtube",
                "title": "YouTube",
                "iconUrl": "https://example.com/youtube.png",
                "supervisionSetting": {
                    "hidden": True,
                    "hiddenSetExplicitly": True,
                },
                "installTimeMillis": "1234567890000",
                "enforcedEnabledStatus": "enabled",
                "appSource": "googlePlay",
                "supervisionCapabilities": [
                    "capabilityAlwaysAllowApp",
                    "capabilityBlock",
                    "capabilityUsageLimit",
                ],
                "adSupportStatus": "adsSupported",
                "iapSupportStatus": "noIap",
                "deviceIds": ["device_1"],
            },
            {
                "packageName": "com.android.calculator2",
                "title": "Calculator",
                "iconUrl": "https://example.com/calc.png",
                "supervisionSetting": {
                    "hidden": False,
                    "hiddenSetExplicitly": False,
                    "alwaysAllowedAppInfo": {
                        "alwaysAllowedState": "alwaysAllowedStateEnabled"
                    },
                },
                "installTimeMillis": "1234567890000",
                "enforcedEnabledStatus": "enabled",
                "appSource": "googlePlay",
                "supervisionCapabilities": ["capabilityAlwaysAllowApp"],
                "adSupportStatus": "noAds",
                "iapSupportStatus": "noIap",
                "deviceIds": ["device_1"],
            },
        ],
        "lastActivityRefreshTimestampMillis": "1234567890000",
        "deviceInfo": [
            {
                "deviceId": "device_1",
                "displayInfo": {
                    "model": "SM-G960F",
                    "friendlyName": "Galaxy S9",
                    "lastActivityTimeMillis": "1234567890000",
                },
                "capabilityInfo": {"capabilities": ["CAPABILITY_APP_USAGE_SESSION"]},
            }
        ],
        "appUsageSessions": [
            {
                "usage": "1800.123",
                "appId": {"androidAppPackageName": "com.spotify.music"},
                "deviceMudId": "device_1",
                "modeType": "NORMAL",
                "date": {"year": 2026, "month": 1, "day": 25},
            }
        ],
    }


@pytest.fixture
def sample_config_csv(tmp_path: Path) -> Path:
    """Create a sample config.csv file."""
    csv_path = tmp_path / "config.csv"
    csv_path.write_text(
        """App,Max Duration,Days,Time Ranges
Calculator,,,
YouTube,0:10,Mon-Fri,
YouTube,0:30,Sat-Sun,
Spotify,1:00,Wed,13:00-18:00
Spotify,1:00,Sat-Sun,09:30-18:00
Google Photos,0:10,,
"""
    )
    return csv_path


@pytest.fixture
def mock_cookies_file(tmp_path: Path, sample_sapisid: str) -> Path:
    """Create a sample Netscape cookies.txt file."""
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text(
        f"""# Netscape HTTP Cookie File
.google.com	TRUE	/	TRUE	0	SAPISID	{sample_sapisid}
.google.com	TRUE	/	TRUE	0	SID	sample_sid_value
"""
    )
    return cookies_path


@pytest.fixture
def mock_env_vars(monkeypatch, sample_sapisid: str) -> dict[str, str]:
    """Set up mock environment variables."""
    env = {
        "FAMILYLINK_SAPISID": sample_sapisid,
        "FAMILYLINK_BROWSER": "firefox",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env
