"""Tests for server configuration."""


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
