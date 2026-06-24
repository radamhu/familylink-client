"""Tests for server configuration."""

import datetime


def test_settings_reads_from_env(monkeypatch):
    """Test that settings are read correctly from environment variables."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost/test")
    monkeypatch.setenv("SECRET_KEY", "test-secret-32-chars-exactly!!!!")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("FAMILYLINK_GOOGLE_EMAIL", "parent@gmail.com")
    monkeypatch.setenv("FAMILYLINK_COOKIES_B64", "dGVzdA==")

    from familylink_server.config import Settings

    s = Settings()
    assert s.database_url == "postgresql+asyncpg://localhost/test"
    assert s.google_client_id == "client-id"
    assert s.familylink_google_email == "parent@gmail.com"
    assert s.cache_ttl_seconds == 900  # default


def test_discord_disabled_by_default():
    """Test that Discord is disabled when no tokens are set."""
    from familylink_server.config import Settings

    s = Settings()
    assert s.discord_enabled is False


def test_discord_enabled_when_all_vars_set(monkeypatch):
    """Test that Discord is enabled when all required vars are set."""
    from familylink_server.config import Settings

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "789012")
    s = Settings()
    assert s.discord_enabled is True
    assert s.discord_guild_id == 123456
    assert s.discord_channel_id == 789012


def test_discord_summary_time_parsed():
    """Test that discord_summary_time is parsed correctly with default time."""
    from familylink_server.config import Settings

    s = Settings()
    t = s.discord_summary_time_parsed
    assert t == datetime.time(20, 0, tzinfo=datetime.UTC)


def test_discord_summary_time_custom(monkeypatch):
    """Test that discord_summary_time can be customized."""
    from familylink_server.config import Settings

    monkeypatch.setenv("DISCORD_SUMMARY_TIME", "08:30")
    s = Settings()
    t = s.discord_summary_time_parsed
    assert t == datetime.time(8, 30, tzinfo=datetime.UTC)
