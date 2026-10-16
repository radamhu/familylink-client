"""Application settings loaded from environment variables."""

import datetime

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = ConfigDict(
        env_file='.env', env_file_encoding='utf-8', extra='ignore'
    )

    database_url: str
    secret_key: str
    google_client_id: str
    google_client_secret: str
    familylink_google_email: str
    familylink_extra_emails: str = ''
    familylink_cookies_b64: str = ''
    familylink_cookie_file: str = ''
    cookie_refresher_url: str = ''
    refresher_api_key: str = ''
    firefox_novnc_url: str = ''
    cache_ttl_seconds: int = 900
    debug: bool = False
    ekreta_ingest_token: str = ''
    local_timezone: str = 'Europe/Budapest'

    discord_bot_token: str | None = None
    discord_guild_id: int | None = None
    discord_channel_id: int | None = None
    discord_allowed_role: str = 'Parent'
    discord_summary_time: str = '20:00'

    ntfy_topics: str = ''
    ntfy_base_url: str = 'http://ntfy-lxzs2xjhmoq2gnriunycf0rq.192.168.0.5.sslip.io'

    @property
    def allowed_emails(self) -> frozenset[str]:
        """Lowercased login allowlist: primary email plus comma-separated extras."""
        emails = [
            self.familylink_google_email,
            *self.familylink_extra_emails.split(','),
        ]
        return frozenset(e.strip().lower() for e in emails if e.strip())

    @property
    def discord_enabled(self) -> bool:
        """True when all three required Discord vars are set."""
        return bool(
            self.discord_bot_token and self.discord_guild_id and self.discord_channel_id
        )

    @property
    def discord_summary_time_parsed(self) -> datetime.time:
        """Parse HH:MM string into a UTC datetime.time."""
        h, m = self.discord_summary_time.split(':')
        return datetime.time(int(h), int(m), tzinfo=datetime.UTC)

    @property
    def ntfy_topics_parsed(self) -> dict[str, str]:
        """Parse 'child_id:topic,child_id:topic' into a dict, skipping malformed pairs."""
        result: dict[str, str] = {}
        for pair in self.ntfy_topics.split(','):
            pair = pair.strip()
            if ':' not in pair:
                continue
            child_id, topic = (part.strip() for part in pair.split(':', 1))
            if child_id and topic:
                result[child_id] = topic
        return result


settings = Settings()
