"""Singleton service wrapping the FamilyLink client with async + cache-aside."""

import asyncio
import logging
import os
from datetime import UTC, datetime

from familylink import FamilyLink
from familylink.models import AppUsage, MembersResponse
from familylink_server.config import settings

logger = logging.getLogger(__name__)


class FamilyLinkService:
    """Wraps the synchronous FamilyLink client for async FastAPI use."""

    def __init__(self) -> None:
        self._client = FamilyLink()
        self._ttl = settings.cache_ttl_seconds
        self._members_cache: tuple[MembersResponse, datetime] | None = None
        self._usage_cache: dict[str, tuple[AppUsage, datetime]] = {}
        self._auth_failed: bool = False

    @property
    def auth_failed(self) -> bool:
        """Return True if the last Google API call failed due to auth."""
        return self._auth_failed

    def set_auth_failed(self, failed: bool) -> None:
        """Set or clear the auth-failed flag."""
        self._auth_failed = failed

    def reinit_with_cookies_b64(self, cookies_b64: str) -> None:
        """Hot-swap the FamilyLink client with a full fresh cookie jar."""
        os.environ['FAMILYLINK_COOKIES_B64'] = cookies_b64
        os.environ.pop('FAMILYLINK_SAPISID', None)
        self._client = FamilyLink()
        self._members_cache = None
        self._usage_cache.clear()
        self._auth_failed = False
        logger.info('FamilyLink client reinitialized with fresh cookie jar')

    def _is_fresh(self, ts: datetime) -> bool:
        return (datetime.now(UTC) - ts).total_seconds() < self._ttl

    async def get_members(self) -> MembersResponse:
        """Return family members, using the cache when still fresh."""
        members_cache: tuple[MembersResponse, datetime] | None = getattr(
            self, '_members_cache', None
        )
        if members_cache and self._is_fresh(members_cache[1]):
            return members_cache[0]
        result = await asyncio.to_thread(self._client.get_members)
        self._members_cache = (result, datetime.now(UTC))
        return result

    async def get_apps_and_usage(self, child_id: str) -> AppUsage:
        """Return app usage for a child, using the cache when still fresh."""
        if not hasattr(self, '_usage_cache'):
            self._usage_cache: dict[str, tuple[AppUsage, datetime]] = {}
        cached = self._usage_cache.get(child_id)
        if cached and self._is_fresh(cached[1]):
            return cached[0]
        result = await asyncio.to_thread(self._client.get_apps_and_usage, child_id)
        self._usage_cache[child_id] = (result, datetime.now(UTC))
        return result

    async def lock_device(self, device_id: str, child_id: str | None = None) -> None:
        """Lock a supervised device."""
        await asyncio.to_thread(
            self._client.lock_device, account_id=child_id, device_id=device_id
        )

    async def unlock_device(self, device_id: str, child_id: str | None = None) -> None:
        """Unlock a supervised device."""
        await asyncio.to_thread(
            self._client.unlock_device, account_id=child_id, device_id=device_id
        )

    async def set_app_limit(
        self, package_name: str, minutes: int, child_id: str | None = None
    ) -> None:
        """Set a daily usage limit for an app and invalidate the usage cache."""
        await asyncio.to_thread(
            self._client.set_app_limit, package_name, minutes, child_id
        )
        if child_id:
            self._usage_cache.pop(child_id, None)
        else:
            self._usage_cache.clear()

    async def block_app(self, package_name: str, child_id: str | None = None) -> None:
        """Block an app and invalidate the usage cache."""
        await asyncio.to_thread(self._client.block_app, package_name, child_id)
        if child_id:
            self._usage_cache.pop(child_id, None)
        else:
            self._usage_cache.clear()

    async def always_allow_app(
        self, package_name: str, child_id: str | None = None
    ) -> None:
        """Always-allow an app and invalidate the usage cache."""
        await asyncio.to_thread(self._client.always_allow_app, package_name, child_id)
        if child_id:
            self._usage_cache.pop(child_id, None)
        else:
            self._usage_cache.clear()


_service: FamilyLinkService | None = None


def init_service() -> FamilyLinkService:
    """Called once at app startup (lifespan). Returns the singleton."""
    global _service
    _service = FamilyLinkService()
    return _service


def get_service() -> FamilyLinkService:
    """FastAPI dependency — returns the singleton."""
    if _service is None:
        raise RuntimeError(
            'FamilyLinkService not initialised — call init_service() in lifespan'
        )
    return _service
