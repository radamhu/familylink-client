"""Cookie and SAPISID resolution for the Family Link API.

Auth priority (first match wins):
  1. FAMILYLINK_COOKIES_B64  — base64-encoded cookies.txt (cloud-native)
  2. FAMILYLINK_SAPISID      — raw SAPISID value only
  3. FAMILYLINK_COOKIE_FILE  — path to Netscape cookies.txt
  4. browser="txt"           — cookie_file_path arg or ./cookies.txt
  5. Per-profile sapisid.txt / cookies.txt (when FAMILYLINK_PROFILES_DIR is set)
  6. browser_cookie3         — local browser extraction (host-only)
"""

import base64
import logging
import os
import tempfile
from http.cookiejar import CookieJar, MozillaCookieJar
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import browser_cookie3
except Exception:
    browser_cookie3 = None


class CookieResolver:
    """Resolves a SAPISID string and optional CookieJar from configured sources."""

    def __init__(
        self,
        browser: str = "firefox",
        cookie_file_path: Path | None = None,
    ) -> None:
        env_browser = os.getenv("FAMILYLINK_BROWSER")
        self._browser = (env_browser or browser or "chrome").lower()
        self._cookie_file_path = cookie_file_path

    def resolve(self) -> tuple[str, CookieJar | None]:
        """Return (sapisid, cookies_jar). Raises ValueError or RuntimeError on failure."""
        profiles_dir = os.getenv("FAMILYLINK_PROFILES_DIR", "").strip()
        cwd = os.getcwd()
        in_profiles_dir = bool(profiles_dir and cwd.startswith(profiles_dir))

        sapisid: str | None = os.getenv("FAMILYLINK_SAPISID", "").strip() or None
        cookies_jar: CookieJar | None = None

        cookies_b64 = os.getenv("FAMILYLINK_COOKIES_B64", "").strip()
        if cookies_b64:
            try:
                raw = base64.b64decode(cookies_b64).decode("utf-8")
                cj = MozillaCookieJar()
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, encoding="utf-8"
                ) as tmp:
                    tmp.write(raw)
                    tmp_path = tmp.name
                cj.load(tmp_path, ignore_discard=True, ignore_expires=True)
                os.unlink(tmp_path)
                cookies_jar = cj
                logger.debug("Loaded cookies from FAMILYLINK_COOKIES_B64")
            except Exception as e:
                raise ValueError(f"Failed to decode FAMILYLINK_COOKIES_B64: {e}") from e

        env_cookie_file = os.getenv("FAMILYLINK_COOKIE_FILE", "").strip()
        if env_cookie_file and not cookies_jar:
            self._cookie_file_path = Path(env_cookie_file)

        if self._browser == "txt" and not cookies_jar:
            if self._cookie_file_path:
                p = Path(self._cookie_file_path)
                if not p.exists() or not p.is_file():
                    raise ValueError(f"Cookie file not found: {p}")
                cj = MozillaCookieJar()
                cj.load(str(p.resolve()), ignore_discard=True, ignore_expires=True)
                cookies_jar = cj
            else:
                p = Path("./cookies.txt")
                if p.exists() and p.is_file():
                    cj = MozillaCookieJar()
                    cj.load(str(p.resolve()), ignore_discard=True, ignore_expires=True)
                    cookies_jar = cj

        if (
            not cookies_jar
            and in_profiles_dir
            and not sapisid
            and self._browser != "txt"
        ):
            for fname in ("sapisid.txt", "SAPISID"):
                p = Path(fname)
                if p.exists() and p.is_file():
                    val = p.read_text(encoding="utf-8").strip()
                    if val:
                        sapisid = val
                        break

        if not cookies_jar and in_profiles_dir:
            p = Path("cookies.txt")
            if p.exists() and p.is_file():
                try:
                    cj = MozillaCookieJar()
                    cj.load(str(p), ignore_discard=True, ignore_expires=True)
                    cookies_jar = cj
                except Exception as e:
                    logger.debug("Failed to load cookies.txt: %s", e)

        if not cookies_jar and self._cookie_file_path:
            if not self._cookie_file_path.exists():
                raise ValueError(f"Cookie file not found: {self._cookie_file_path}")
            if not self._cookie_file_path.is_file():
                raise ValueError(f"Cookie file is not a file: {self._cookie_file_path}")
            try:
                cj = MozillaCookieJar()
                cj.load(
                    str(self._cookie_file_path.resolve()),
                    ignore_discard=True,
                    ignore_expires=True,
                )
                cookies_jar = cj
            except Exception as e:
                logger.debug("Failed to load cookie_file_path: %s", e)

        if not sapisid and not cookies_jar:
            if in_profiles_dir:
                raise RuntimeError(
                    "No cached SAPISID/cookies found in profile dir and browser access is "
                    "disabled in container. Provide sapisid.txt or cookies.txt under the "
                    "profile folder, or set FAMILYLINK_SAPISID/FAMILYLINK_COOKIE_FILE."
                )
            if browser_cookie3 is None:
                raise RuntimeError(
                    "browser_cookie3 not available and no cached session found"
                )
            cookie_kwargs: dict = {}
            if self._cookie_file_path:
                cookie_kwargs["cookie_file"] = str(self._cookie_file_path.resolve())
            cookies_jar = getattr(browser_cookie3, self._browser)(**cookie_kwargs)

        if not sapisid and cookies_jar is not None:
            for cookie in cookies_jar:
                if cookie.name == "SAPISID" and cookie.domain == ".google.com":
                    sapisid = cookie.value
                    break

        if not sapisid:
            raise ValueError(
                "Could not find SAPISID. "
                "On host: ensure you're signed in (Chrome/Firefox) or pass FAMILYLINK_COOKIE_FILE. "
                "In Docker: set FAMILYLINK_COOKIES_B64 or FAMILYLINK_SAPISID."
            )

        return sapisid, cookies_jar
