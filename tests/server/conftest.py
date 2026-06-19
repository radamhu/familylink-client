"""Shared fixtures for server tests."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/familylink_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-bytes-exactly!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("FAMILYLINK_GOOGLE_EMAIL", "parent@gmail.com")
os.environ.setdefault("FAMILYLINK_COOKIES_B64", "dGVzdA==")
