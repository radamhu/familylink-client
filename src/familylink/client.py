"""Family Link API client."""

import hashlib
import json
import logging
import time
from pathlib import Path

import httpx

from familylink import parsers
from familylink.auth import CookieResolver
from familylink.models import AppUsage, MembersResponse

logger = logging.getLogger(__name__)


class SessionExpiredError(RuntimeError):
    """Google session has expired or been invalidated.

    Re-export cookies and update FAMILYLINK_COOKIES_B64 or FAMILYLINK_COOKIE_FILE.
    Run: familylink export-cookies --base64
    """


def _generate_sapisidhash(sapisid: str, origin: str) -> str:
    ts = int(time.time() * 1000)  # milliseconds
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"{ts}_{digest}"


class FamilyLink:
    """Client to interact with Google Family Link."""

    BASE_URL = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
    ORIGIN = "https://familylink.google.com"

    def __init__(
        self,
        account_id: str | None = None,
        browser: str = "firefox",
        cookie_file_path: Path | None = None,
    ) -> None:
        self.account_id = account_id
        sapisid, cookies_jar = CookieResolver(browser, cookie_file_path).resolve()
        self._headers = {
            "User-Agent": "Mozilla/5.0",
            "Origin": self.ORIGIN,
            "Content-Type": "application/json+protobuf",
            "X-Goog-Api-Key": "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw",
            "Authorization": f"SAPISIDHASH {_generate_sapisidhash(sapisid, self.ORIGIN)}",
        }
        self._cookies = cookies_jar
        self._session = httpx.Client(
            headers=self._headers, cookies=self._cookies, timeout=30
        )

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _get(self, path: str, params: list | dict | None = None) -> httpx.Response:
        r = self._session.get(f"{self.BASE_URL}{path}", params=params)
        if r.status_code in (401, 403):
            raise SessionExpiredError(
                f"HTTP {r.status_code} — session expired. "
                "Re-export: familylink export-cookies --base64"
            )
        r.raise_for_status()
        return r

    def _post(self, path: str, content: str) -> httpx.Response:
        r = self._session.post(f"{self.BASE_URL}{path}", content=content)
        if r.status_code in (401, 403):
            raise SessionExpiredError(
                f"HTTP {r.status_code} — session expired. "
                "Re-export: familylink export-cookies --base64"
            )
        r.raise_for_status()
        return r

    def _ensure_account_id(self) -> str:
        if self.account_id:
            return self.account_id
        for mem in self.get_members().members:
            if (
                mem.member_supervision_info
                and mem.member_supervision_info.is_supervised_member
            ):
                return mem.user_id
        raise ValueError("No supervised account found; set account_id explicitly")

    # ── Read API ──────────────────────────────────────────────────────────────

    def get_members(self) -> MembersResponse:
        """List family members for the authenticated parent."""
        data = self._get("/families/mine/members").json()
        if isinstance(data, list):
            data = parsers.parse_members_response(data)
        return MembersResponse.model_validate(data)

    def get_apps_and_usage(self, child_id: str) -> AppUsage:
        """Get apps and usage information for a child."""
        params = [
            ("capabilities", "CAPABILITY_APP_USAGE_SESSION"),
            ("capabilities", "CAPABILITY_SUPERVISION_CAPABILITIES"),
        ]
        data = self._get(f"/people/{child_id}/appsandusage", params).json()
        if isinstance(data, list):
            data = parsers.parse_apps_and_usage(data)
        return AppUsage.model_validate(data)

    def get_time_limit(self, child_id: str) -> dict:
        """Get time limit for a child."""
        return self._get(f"/people/{child_id}/timeLimit").json()

    def get_applied_time_limits(self, child_id: str) -> dict:
        """Get applied time limits for a child."""
        return self._get(f"/people/{child_id}/appliedTimeLimits").json()

    def get_time_limits(self, account_id: str | None = None) -> dict:
        """Get applied time limits for a child (today)."""
        aid = account_id or self._ensure_account_id()
        r = self._session.get(
            f"{self.BASE_URL}/people/{aid}/appliedTimeLimits",
            headers={"Content-Type": "application/json"},
        )
        if r.status_code in (401, 403):
            raise SessionExpiredError(
                f"HTTP {r.status_code} — session expired. "
                "Re-export: familylink export-cookies --base64"
            )
        r.raise_for_status()
        return r.json()

    def print_usage(self) -> None:
        """Print usage for all family members."""
        for m in self.get_members().members:
            p = m.profile
            print(f"- {p.display_name} | {p.email} | user_id={m.user_id}")  # noqa: T201

    # ── Device operations ─────────────────────────────────────────────────────

    def set_time_limits_device(
        self,
        account_id: str | None = None,
        device_id: str = "",
        period_id: str = "",
        time_in_minutes: int = 0,
    ) -> dict:
        """Set daily time limit (minutes) for a device."""
        aid = account_id or self._ensure_account_id()
        payload = json.dumps(
            [
                None,
                aid,
                [
                    [
                        None,
                        None,
                        8,
                        device_id,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        [2, time_in_minutes, period_id],
                    ]
                ],
                [1],
            ]
        )
        return self._post(
            f"/people/{aid}/timeLimitOverrides:batchCreate", payload
        ).json()

    def disable_time_limits_device(
        self,
        account_id: str | None = None,
        device_id: str = "",
        period_id: str = "",
        time_in_minutes: int = 0,
    ) -> dict:
        """Disable all time limits for a device (today)."""
        aid = account_id or self._ensure_account_id()
        payload = json.dumps(
            [
                None,
                aid,
                [
                    [
                        None,
                        None,
                        8,
                        device_id,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        [1, time_in_minutes, period_id],
                    ]
                ],
                [1],
            ]
        )
        return self._post(
            f"/people/{aid}/timeLimitOverrides:batchCreate", payload
        ).json()

    def enable_time_limits_device(
        self,
        account_id: str | None = None,
        device_id: str = "",
        period_id: str = "",
        time_in_minutes: int = 0,
    ) -> dict:
        """Re-enable previous time limits for a device."""
        return self.set_time_limits_device(
            account_id, device_id, period_id, time_in_minutes
        )

    def lock_device(self, account_id: str | None = None, device_id: str = "") -> dict:
        """Lock a device."""
        aid = account_id or self._ensure_account_id()
        return self._post(
            f"/people/{aid}/timeLimitOverrides:batchCreate",
            json.dumps([None, aid, [[None, None, 1, device_id]], [1]]),
        ).json()

    def unlock_device(self, account_id: str | None = None, device_id: str = "") -> dict:
        """Unlock a device."""
        aid = account_id or self._ensure_account_id()
        return self._post(
            f"/people/{aid}/timeLimitOverrides:batchCreate",
            json.dumps([None, aid, [[None, None, 4, device_id]], [1]]),
        ).json()

    def enable_downtime_device(
        self,
        account_id: str | None = None,
        device_id: str = "",
        start_hour: int = 0,
        start_minute: int = 0,
        end_hour: int = 0,
        end_minute: int = 0,
        period_id: str = "",
    ) -> dict:
        """Enable downtime for a device (today)."""
        aid = account_id or self._ensure_account_id()
        payload = json.dumps(
            [
                None,
                aid,
                [
                    [
                        None,
                        None,
                        9,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        [
                            2,
                            [start_hour, start_minute],
                            [end_hour, end_minute],
                            period_id,
                        ],
                    ]
                ],
                [1],
            ]
        )
        return self._post(
            f"/people/{aid}/timeLimitOverrides:batchCreate", payload
        ).json()

    def disable_downtime_device(
        self,
        account_id: str | None = None,
        device_id: str = "",
        start_hour: int = 0,
        start_minute: int = 0,
        end_hour: int = 0,
        end_minute: int = 0,
        period_id: str = "",
    ) -> dict:
        """Disable downtime for a device (today)."""
        aid = account_id or self._ensure_account_id()
        payload = json.dumps(
            [
                None,
                aid,
                [
                    [
                        None,
                        None,
                        9,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        [
                            1,
                            [start_hour, start_minute],
                            [end_hour, end_minute],
                            period_id,
                        ],
                    ]
                ],
                [1],
            ]
        )
        return self._post(
            f"/people/{aid}/timeLimitOverrides:batchCreate", payload
        ).json()

    # ── App supervision ───────────────────────────────────────────────────────────

    def set_app_limit(
        self,
        package_name: str,
        minutes: int,
        child_id: str | None = None,
    ) -> dict:
        """Set a daily time limit (minutes) on an app."""
        aid = child_id or self._ensure_account_id()
        data = [[package_name], None, [minutes, 1]]
        return self._post(
            f"/people/{aid}/apps:updateRestrictions", json.dumps([aid, [data]])
        ).json()

    def block_app(self, package_name: str, child_id: str | None = None) -> dict:
        """Block an app (hidden from child)."""
        aid = child_id or self._ensure_account_id()
        data = [[package_name], [1]]
        return self._post(
            f"/people/{aid}/apps:updateRestrictions", json.dumps([aid, [data]])
        ).json()

    def always_allow_app(self, package_name: str, child_id: str | None = None) -> dict:
        """Set an app to always allowed (no daily limit)."""
        aid = child_id or self._ensure_account_id()
        data = [[package_name], None, None, [1]]
        return self._post(
            f"/people/{aid}/apps:updateRestrictions", json.dumps([aid, [data]])
        ).json()

    def remove_app_limit(self, package_name: str, child_id: str | None = None) -> dict:
        """Remove any daily time limit from an app (returns it to blocked)."""
        aid = child_id or self._ensure_account_id()
        data = [[package_name], [1]]
        return self._post(
            f"/people/{aid}/apps:updateRestrictions", json.dumps([aid, [data]])
        ).json()
