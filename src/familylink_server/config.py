"""Application settings loaded from environment variables."""

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


settings = Settings()
