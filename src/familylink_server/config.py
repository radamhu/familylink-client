"""Application settings loaded from environment variables."""

import datetime

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = ConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str
    secret_key: str
    google_client_id: str
    google_client_secret: str
    familylink_google_email: str
    familylink_cookies_b64: str = ""
    familylink_cookie_file: str = ""
    familylink_sapisid: str = ""
    cache_ttl_seconds: int = 900
    debug: bool = False

    discord_bot_token: str | None = None
    discord_guild_id: int | None = None
    discord_channel_id: int | None = None
    discord_allowed_role: str = "Parent"
    discord_summary_time: str = "20:00"

    @property
    def discord_enabled(self) -> bool:
        """True when all three required Discord vars are set."""
        return bool(
            self.discord_bot_token and self.discord_guild_id and self.discord_channel_id
        )

    @property
    def discord_summary_time_parsed(self) -> datetime.time:
        """Parse HH:MM string into a UTC datetime.time."""
        h, m = self.discord_summary_time.split(":")
        return datetime.time(int(h), int(m), tzinfo=datetime.UTC)


settings = Settings()
