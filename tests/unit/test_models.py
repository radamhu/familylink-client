"""Tests for familylink models."""

from familylink.models import AppUsage, MembersResponse


def test_members_response_model_validate_alias_keys():
    """Test MembersResponse.model_validate with camelCase alias keys."""
    data = {
        "members": [
            {
                "userId": "u1",
                "role": "child",
                "profile": {
                    "displayName": "Alice",
                    "profileImageUrl": "",
                    "email": "alice@example.com",
                    "familyName": "Smith",
                    "givenName": "Alice",
                    "defaultProfileImageUrl": "",
                },
                "state": "1",
            }
        ],
        "apiHeader": {"serverTimestampMillis": "12345"},
        "myUserId": "parent1",
    }
    result = MembersResponse.model_validate(data)
    assert result.my_user_id == "parent1"
    assert result.members[0].profile.display_name == "Alice"


def test_members_response_api_header_snake_case():
    """Test nested ApiHeader conversion to snake_case."""
    result = MembersResponse.model_validate(
        {
            "members": [],
            "apiHeader": {"serverTimestampMillis": "0"},
            "myUserId": "p1",
        }
    )
    assert result.api_header.server_timestamp_millis == "0"


def test_app_usage_model_validate_alias_keys():
    """Test AppUsage.model_validate with camelCase alias keys."""
    data = {
        "apiHeader": {"serverTimestampMillis": "1"},
        "apps": [],
        "lastActivityRefreshTimestampMillis": "0",
        "deviceInfo": [],
        "appUsageSessions": [],
    }
    result = AppUsage.model_validate(data)
    assert result.apps == []
