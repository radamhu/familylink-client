"""Family Link API client (patched for Docker profile-based auth).

- Supports per-profile `sapisid.txt`, `cookies.txt`, and `authuser.txt`.
- Avoids browser_cookie3 in containers (no DBus/keychain).
- Still works on host with browser_cookie3 if not in a profiles dir.
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path

import httpx

try:
    import browser_cookie3  # may be unavailable in Docker
except Exception:
    browser_cookie3 = None

from http.cookiejar import CookieJar, MozillaCookieJar

from familylink.models import MembersResponse

logger = logging.getLogger(__name__)

def _generate_sapisidhash(sapisid: str, origin: str) -> str:
    """Generate the SAPISIDHASH value for Authorization header.
    Format: f"{timestamp} {sha1(f'{timestamp} {sapisid} {origin}')}"
    """
    # ts = int(time.time())
    # to_hash = f"{ts} {sapisid} {origin}".encode("utf-8")
    # digest = hashlib.sha1(to_hash).hexdigest()
    # return f"{ts}_{digest}"  # underscore is accepted by many Google backends

    ts = int(time.time() * 1000)  # milliseconds
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"{ts}_{digest}"  # underscore, not space

    # ts = int(time.time() * 1000)
    # digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    # return f"{ts}_{digest}"

    # ts = int(time.time())
    # msg = f"{ts} {sapisid} {origin}".encode("utf-8")
    # digest = hashlib.sha1(msg).hexdigest()
    # return f"{ts} {digest}"  # <— space, not underscore

class FamilyLink:
    """Client to interact with Google Family Link."""

    BASE_URL = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
    ORIGIN = "https://familylink.google.com"

    def __init__(
        self,
        account_id: str | None = None,
        browser: str = "firefox",
        cookie_file_path: Path | None = None,
    ):
        """Initialize the Family Link client.

        Args:
            account_id: The Google account ID to manage
            browser: The browser to get cookies from if sapisid not provided
            cookie_file_path: Optional path to a cookie file to load
        """
        self.account_id = account_id

        # --- Environment & profile context ---
        env_browser = os.getenv("FAMILYLINK_BROWSER")
        browser = (env_browser or browser or "chrome").lower()

        profiles_dir = os.getenv("FAMILYLINK_PROFILES_DIR", "").strip()
        cwd = os.getcwd()
        in_profiles_dir = bool(profiles_dir and cwd.startswith(profiles_dir))

        # Per-profile authuser (account index)
        authuser = os.getenv("FAMILYLINK_AUTHUSER", "").strip()
        if in_profiles_dir and not authuser:
            p = Path("authuser.txt")
            if p.exists() and p.is_file():
                authuser = p.read_text(encoding="utf-8").strip()
        if not authuser:
            authuser = "0"

        # --- Cookie/SAPISID sources ---
        sapisid = os.getenv("FAMILYLINK_SAPISID", "").strip() or None
        cookies_jar: CookieJar | None = None

        # ENV cookie file overrides
        env_cookie_file = os.getenv("FAMILYLINK_COOKIE_FILE", "").strip()
        if env_cookie_file:
            cookie_file_path = Path(env_cookie_file)

        # browser="txt": cookies from file only (no browser sync; e.g. Home Assistant)
        if browser == "txt":
            p = Path(cookie_file_path) if cookie_file_path else Path("./cookies.txt")
            if not p.exists() or not p.is_file():
                raise ValueError(f"Cookie file not found: {p}")
            cj = MozillaCookieJar()
            cj.load(str(p.resolve()), ignore_discard=True, ignore_expires=True)
            cookies_jar = cj

        # If running under profile dir, first try local sapisid/cookies files
        if not cookies_jar and in_profiles_dir and not sapisid and browser != "txt":
            # a) sapisid.txt or SAPISID file (raw value)
            for fname in ("sapisid.txt", "SAPISID"):
                p = Path(fname)
                if p.exists() and p.is_file():
                    val = p.read_text(encoding="utf-8").strip()
                    if val:
                        sapisid = val
                        break

        # Always try cookies.txt if present (even if sapisid already set)
        if not cookies_jar and in_profiles_dir:
            p = Path("cookies.txt")
            if p.exists() and p.is_file():
                try:
                    cj = MozillaCookieJar()
                    cj.load(str(p), ignore_discard=True, ignore_expires=True)
                    cookies_jar = cj
                except Exception as e:
                    logger.debug("Failed to load cookies.txt: %s", e)

        # Fallback: explicit cookie file
        if not cookies_jar and cookie_file_path:
            if not cookie_file_path.exists():
                raise ValueError(f"Cookie file not found: {cookie_file_path}")
            if not cookie_file_path.is_file():
                raise ValueError(f"Cookie file is not a file: {cookie_file_path}")
            try:
                cj = MozillaCookieJar()
                cj.load(str(cookie_file_path.resolve()), ignore_discard=True, ignore_expires=True)
                cookies_jar = cj
            except Exception as e:
                logger.debug("Failed to load cookie_file_path: %s", e)

        # Last resort: read from local browser (only when not in container profile dir)
        if not sapisid and not cookies_jar:
            if in_profiles_dir:
                raise RuntimeError(
                    "No cached SAPISID/cookies found in profile dir and browser access is disabled in container. "
                    "Provide sapisid.txt or cookies.txt under the profile folder, or set FAMILYLINK_SAPISID/FAMILYLINK_COOKIE_FILE."
                )
            if browser_cookie3 is None:
                raise RuntimeError("browser_cookie3 not available and no cached session found")
            cookie_kwargs = {}
            if cookie_file_path:
                cookie_kwargs["cookie_file"] = str(cookie_file_path.resolve())
            cookies_jar = getattr(browser_cookie3, browser)(**cookie_kwargs)

        # Extract SAPISID from whatever cookie jar we have (if not from sapisid.txt)
        if not sapisid and cookies_jar is not None:
            for cookie in cookies_jar:
                if cookie.name == "SAPISID" and cookie.domain == ".google.com":
                    sapisid = cookie.value
                    break

        if not sapisid:
            raise ValueError(
                "Could not find SAPISID. "
                "On host: ensure you’re signed in (Chrome/Firefox) or pass FAMILYLINK_COOKIE_FILE. "
                "In Docker: put sapisid.txt (with the raw SAPISID value) or cookies.txt in the profile folder, "
                "or set FAMILYLINK_SAPISID."
            )

        # --- Build headers/session ---
        sapisidhash = _generate_sapisidhash(sapisid, self.ORIGIN)

        # self._headers = {
        #     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        #     "Origin": self.ORIGIN,
        #     "Content-Type": "application/json+protobuf",
        #     "X-Goog-Api-Key": "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw",
        #     "Authorization": authorization,
        #     "X-Goog-AuthUser": authuser,
        # }

        self._headers = {
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://familylink.google.com",  # match working request
            # no Referer
            # no X-Goog-AuthUser
            "Content-Type": "application/json+protobuf",
            "X-Goog-Api-Key": "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw",
            "Authorization": f"SAPISIDHASH {_generate_sapisidhash(sapisid, 'https://familylink.google.com')}",
        }

        self._cookies = cookies_jar
        self._session = httpx.Client(headers=self._headers, cookies=self._cookies, timeout=30)
        self._app_names = {}

    # ----------------- minimal API methods -----------------
    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        url = f"{self.BASE_URL}{path}"
        r = self._session.get(url, params=params)
        r.raise_for_status()
        return r

    def _post(self, path: str, content: str) -> httpx.Response:
        r = self._session.post(f"{self.BASE_URL}{path}", content=content)
        r.raise_for_status()
        return r

    def _ensure_account_id(self) -> str:
        if self.account_id:
            return self.account_id
        m = self.get_members()
        for mem in m.members:
            if mem.user_id != m.my_user_id:
                return mem.user_id
        raise ValueError("No child account; set account_id explicitly")

    def get_members(self) -> MembersResponse:
        """List family members for the authenticated parent."""
        resp = self._get("/families/mine/members")
        data = resp.json()
        return MembersResponse(**data)

    # Optional helper to print usage if your models implement it differently
    def print_usage(self) -> None:
        members = self.get_members().members
        for m in members:
            p = getattr(m, "profile", None)
            if not p:
                continue
            print(f"- {getattr(p,'display_name',None)} | {getattr(p,'email',None)} | user_id={getattr(m,'user_id',None)}")

    def get_apps_and_usage(self, child_id: str) -> dict:
        # Minimal GET; our session already has the right headers (Origin, SAPISIDHASH, etc.)
        path = f"/people/{child_id}/appsandusage"
        params = [
            ("capabilities", "CAPABILITY_APP_USAGE_SESSION"),
            ("capabilities", "CAPABILITY_SUPERVISION_CAPABILITIES"),
        ]
        r = self._session.get(f"{self.BASE_URL}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def get_time_limit(self, child_id: str) -> dict:
        r = self._session.get(f"{self.BASE_URL}/people/{child_id}/timeLimit")
        r.raise_for_status()
        return r.json()

    def get_applied_time_limits(self, child_id: str) -> dict:
        r = self._session.get(f"{self.BASE_URL}/people/{child_id}/appliedTimeLimits")
        r.raise_for_status()
        return r.json()

    def get_time_limits(self, account_id: str | None = None) -> dict:
        """Get applied time limits for a child (today)."""
        aid = account_id or self._ensure_account_id()
        r = self._session.get(
            f"{self.BASE_URL}/people/{aid}/appliedTimeLimits",
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()

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
                    ],
                ],
                [1],
            ]
        )
        r = self._post(f"/people/{aid}/timeLimitOverrides:batchCreate", payload)
        return r.json()

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
                    ],
                ],
                [1],
            ]
        )
        r = self._post(f"/people/{aid}/timeLimitOverrides:batchCreate", payload)
        return r.json()

    def enable_time_limits_device(
        self,
        account_id: str | None = None,
        device_id: str = "",
        period_id: str = "",
        time_in_minutes: int = 0,
    ) -> dict:
        """Re-enable previous time limits for a device (calls set_time_limits_device)."""
        return self.set_time_limits_device(
            account_id, device_id, period_id, time_in_minutes
        )

    def lock_device(
        self,
        account_id: str | None = None,
        device_id: str = "",
    ) -> dict:
        """Lock a device."""
        aid = account_id or self._ensure_account_id()
        payload = json.dumps([None, aid, [[None, None, 1, device_id]], [1]])
        r = self._post(f"/people/{aid}/timeLimitOverrides:batchCreate", payload)
        return r.json()

    def unlock_device(
        self,
        account_id: str | None = None,
        device_id: str = "",
    ) -> dict:
        """Unlock a device."""
        aid = account_id or self._ensure_account_id()
        payload = json.dumps([None, aid, [[None, None, 4, device_id]], [1]])
        r = self._post(f"/people/{aid}/timeLimitOverrides:batchCreate", payload)
        return r.json()

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
                            [start_hour, end_minute],
                            [end_hour, end_minute],
                            period_id,
                        ],
                    ],
                ],
                [1],
            ]
        )
        r = self._post(f"/people/{aid}/timeLimitOverrides:batchCreate", payload)
        return r.json()

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
                            [start_hour, end_minute],
                            [end_hour, end_minute],
                            period_id,
                        ],
                    ],
                ],
                [1],
            ]
        )
        r = self._post(f"/people/{aid}/timeLimitOverrides:batchCreate", payload)
        return r.json()
