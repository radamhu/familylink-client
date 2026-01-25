"""Unit tests for Pydantic models."""

from familylink.models import (
    AlwaysAllowedState,
    App,
    AppSupervisionCapability,
    AppUsage,
    AppUsageSession,
    MembersResponse,
    Profile,
    SupervisionSetting,
    UsageLimit,
)


class TestEnums:
    """Test enum definitions."""

    def test_app_supervision_capability_values(self):
        """Test AppSupervisionCapability enum values."""
        assert AppSupervisionCapability.ALWAYS_ALLOW == "capabilityAlwaysAllowApp"
        assert AppSupervisionCapability.BLOCK == "capabilityBlock"
        assert AppSupervisionCapability.USAGE_LIMIT == "capabilityUsageLimit"

    def test_always_allowed_state_values(self):
        """Test AlwaysAllowedState enum values."""
        assert AlwaysAllowedState.ENABLED == "alwaysAllowedStateEnabled"


class TestUsageLimit:
    """Test UsageLimit model."""

    def test_usage_limit_valid(self):
        """Test valid UsageLimit creation."""
        data = {"dailyUsageLimitMins": 30, "enabled": True}
        limit = UsageLimit(**data)
        assert limit.daily_usage_limit_mins == 30
        assert limit.enabled is True

    def test_usage_limit_disabled(self):
        """Test UsageLimit when disabled."""
        data = {"dailyUsageLimitMins": 0, "enabled": False}
        limit = UsageLimit(**data)
        assert limit.daily_usage_limit_mins == 0
        assert limit.enabled is False


class TestSupervisionSetting:
    """Test SupervisionSetting model."""

    def test_supervision_setting_with_usage_limit(self):
        """Test SupervisionSetting with usage limit."""
        data = {
            "hidden": False,
            "hiddenSetExplicitly": False,
            "usageLimit": {"dailyUsageLimitMins": 60, "enabled": True},
        }
        setting = SupervisionSetting(**data)
        assert setting.hidden is False
        assert setting.usage_limit.daily_usage_limit_mins == 60

    def test_supervision_setting_blocked(self):
        """Test SupervisionSetting for blocked app."""
        data = {"hidden": True, "hiddenSetExplicitly": True}
        setting = SupervisionSetting(**data)
        assert setting.hidden is True
        assert setting.usage_limit is None

    def test_supervision_setting_always_allowed(self):
        """Test SupervisionSetting for always allowed app."""
        data = {
            "hidden": False,
            "hiddenSetExplicitly": False,
            "alwaysAllowedAppInfo": {"alwaysAllowedState": "alwaysAllowedStateEnabled"},
        }
        setting = SupervisionSetting(**data)
        assert setting.always_allowed_app_info.always_allowed_state == (
            AlwaysAllowedState.ENABLED
        )


class TestApp:
    """Test App model."""

    def test_app_valid_data(self):
        """Test App model with valid data."""
        data = {
            "packageName": "com.spotify.music",
            "title": "Spotify",
            "iconUrl": "https://example.com/icon.png",
            "supervisionSetting": {
                "hidden": False,
                "hiddenSetExplicitly": False,
                "usageLimit": {"dailyUsageLimitMins": 30, "enabled": True},
            },
            "installTimeMillis": "1234567890000",
            "enforcedEnabledStatus": "enabled",
            "appSource": "googlePlay",
            "supervisionCapabilities": ["capabilityUsageLimit", "capabilityBlock"],
            "adSupportStatus": "adsSupported",
            "iapSupportStatus": "iapSupported",
            "deviceIds": ["device_1"],
        }
        app = App(**data)
        assert app.package_name == "com.spotify.music"
        assert app.title == "Spotify"
        assert app.supervision_setting.usage_limit.daily_usage_limit_mins == 30

    def test_app_missing_optional_fields(self):
        """Test App model with missing optional fields."""
        data = {
            "packageName": "com.test.app",
            "title": "Test App",
            "iconUrl": "https://example.com/icon.png",
            "supervisionSetting": {"hidden": False, "hiddenSetExplicitly": False},
            "installTimeMillis": "1234567890000",
            "enforcedEnabledStatus": "enabled",
            "appSource": "googlePlay",
            "supervisionCapabilities": ["capabilityBlock"],
            "adSupportStatus": "noAds",
            "iapSupportStatus": "noIap",
        }
        app = App(**data)
        assert app.device_ids == []


class TestProfile:
    """Test Profile model."""

    def test_profile_valid_data(self):
        """Test Profile model with valid data."""
        data = {
            "displayName": "John Doe",
            "profileImageUrl": "https://example.com/profile.jpg",
            "email": "john@example.com",
            "familyName": "Doe",
            "givenName": "John",
            "standardGender": "male",
            "birthday": {"day": 15, "month": 6, "year": 2010},
            "defaultProfileImageUrl": "https://example.com/default.jpg",
        }
        profile = Profile(**data)
        assert profile.display_name == "John Doe"
        assert profile.email == "john@example.com"
        assert profile.birthday.year == 2010

    def test_profile_optional_gender(self):
        """Test Profile model with optional gender field."""
        data = {
            "displayName": "John Doe",
            "profileImageUrl": "https://example.com/profile.jpg",
            "email": "john@example.com",
            "familyName": "Doe",
            "givenName": "John",
            "defaultProfileImageUrl": "https://example.com/default.jpg",
        }
        profile = Profile(**data)
        assert profile.standard_gender is None


class TestMembersResponse:
    """Test MembersResponse model."""

    def test_members_response_valid(self, mock_members_response):
        """Test MembersResponse with valid data."""
        response = MembersResponse(**mock_members_response)
        assert len(response.members) == 2
        assert response.my_user_id == "parent_123"
        assert response.members[0].role == "parent"
        assert response.members[1].role == "child"


class TestAppUsage:
    """Test AppUsage model."""

    def test_app_usage_valid(self, mock_apps_response):
        """Test AppUsage model with valid data."""
        usage = AppUsage(**mock_apps_response)
        assert len(usage.apps) == 3
        assert len(usage.device_info) == 1
        assert usage.device_info[0].device_id == "device_1"

    def test_get_app_title(self, mock_apps_response):
        """Test get_app_title helper method."""
        usage = AppUsage(**mock_apps_response)
        assert usage.get_app_title("com.spotify.music") == "Spotify"
        assert usage.get_app_title("com.google.android.youtube") == "YouTube"
        assert usage.get_app_title("unknown.package") == "Unknown"


class TestAppUsageSession:
    """Test AppUsageSession model."""

    def test_app_usage_session_valid(self):
        """Test AppUsageSession with valid data."""
        data = {
            "usage": "1800.123",
            "appId": {"androidAppPackageName": "com.test.app"},
            "deviceMudId": "device_1",
            "modeType": "NORMAL",
            "date": {"year": 2026, "month": 1, "day": 25},
        }
        session = AppUsageSession(**data)
        assert session.usage == "1800.123"
        assert session.app_id.android_app_package_name == "com.test.app"
        assert session.date.year == 2026
