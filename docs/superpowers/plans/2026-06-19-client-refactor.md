# Family Link Client Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the `familylink` package — extract auth and parser logic into dedicated modules, migrate models to native Pydantic v2, and implement the four missing app management methods (`set_app_limit`, `block_app`, `always_allow_app`, `remove_app_limit`).

**Architecture:** `CookieResolver` in `auth.py` handles all cookie/SAPISID resolution; `parsers.py` holds the three `_parse_*` functions; `client.py` becomes a thin orchestrator importing from both. Models migrate from the `pydantic.v1` compat shim to native Pydantic v2, with `model_validate()` used everywhere alias-keyed dicts are constructed.

**Tech Stack:** Python 3.12, Pydantic v2, httpx, pytest, pytest-httpx

## Global Constraints

- Python ≥ 3.12
- Pydantic ≥ 2.0 — no `pydantic.v1` imports anywhere after this plan
- Public API stays backward-compatible: `FamilyLink` and `SessionExpiredError` must remain importable from `familylink`
- TDD: write the failing test before writing implementation code
- One commit per task minimum

---

### Task 1: Migrate models.py to Pydantic v2

**Files:**
- Modify: `src/familylink/models.py`
- Create/Modify: `tests/unit/test_models.py`

**Interfaces:**
- Produces: `MembersResponse.model_validate(dict)`, `AppUsage.model_validate(dict)` — called in Tasks 3 and 4

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_models.py
from familylink.models import ApiHeader, AppUsage, Member, MembersResponse, Profile


def test_members_response_model_validate_alias_keys():
    data = {
        "members": [
            {
                "userId": "u1",
                "role": "child",
                "profile": {
                    "displayName": "Alice",
                    "profileImageUrl": "",
                    "email": "alice@example.com",
                    "familyName": "Smith",
                    "givenName": "Alice",
                    "defaultProfileImageUrl": "",
                },
                "state": "1",
            }
        ],
        "apiHeader": {"serverTimestampMillis": "12345"},
        "myUserId": "parent1",
    }
    result = MembersResponse.model_validate(data)
    assert result.my_user_id == "parent1"
    assert result.members[0].profile.display_name == "Alice"


def test_members_response_api_header_snake_case():
    result = MembersResponse.model_validate({
        "members": [],
        "apiHeader": {"serverTimestampMillis": "0"},
        "myUserId": "p1",
    })
    assert result.api_header.server_timestamp_millis == "0"


def test_app_usage_model_validate_alias_keys():
    data = {
        "apiHeader": {"serverTimestampMillis": "1"},
        "apps": [],
        "lastActivityRefreshTimestampMillis": "0",
        "deviceInfo": [],
        "appUsageSessions": [],
    }
    result = AppUsage.model_validate(data)
    assert result.apps == []
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/unit/test_models.py -v
```

Expected: `ImportError` or `ValidationError` because `pydantic.v1` constructs by alias differently from v2.

- [ ] **Step 3: Replace imports and add model_config to every class**

At the top of `src/familylink/models.py`, replace:

```python
# REMOVE these two lines:
from pydantic.v1 import BaseModel, Field
from typing import Optional
```

Add:

```python
from pydantic import BaseModel, ConfigDict, Field
```

Add `model_config = ConfigDict(populate_by_name=True)` as the **first line** inside every class body. The classes that need it (all classes with `Field(alias=...)`):

`AlwaysAllowedAppInfo`, `UsageLimit`, `SupervisionSetting`, `App`, `AppId`, `UsageDate`, `AppUsageSession`, `DeviceDisplayInfo`, `DeviceCapabilityInfo`, `DeviceInfo`, `ApiHeader`, `AppUsage`, `Birthday`, `Profile`, `MemberSupervisionInfo`, `MemberAttributes`, `UiCustomizations`, `Member`, `MembersResponse`

Example (repeat this pattern for each class):

```python
class ApiHeader(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server_timestamp_millis: str = Field(alias="serverTimestampMillis")
```

Also fix the one remaining `Optional` import on `Profile`:

```python
# BEFORE
standard_gender: Optional[str] = Field(default=None, alias="standardGender")
# AFTER
standard_gender: str | None = Field(default=None, alias="standardGender")
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
pytest tests/unit/test_models.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink/models.py tests/unit/test_models.py
git commit -m "feat: migrate models to native Pydantic v2"
```

---

### Task 2: Extract parsers.py

**Files:**
- Create: `src/familylink/parsers.py`
- Modify: `src/familylink/client.py` (remove the three static methods, add import)
- Create/Modify: `tests/unit/test_parsers.py`

**Interfaces:**
- Produces:
  - `parse_members_response(data: list) -> dict` — returns dict with camelCase keys matching `MembersResponse` aliases
  - `parse_apps_and_usage(data: list) -> dict` — returns dict matching `AppUsage` aliases
  - `parse_time_limit(data: list) -> dict[int, dict]` — returns `{day_int: {"avail_start": "HH:MM", "avail_end": "HH:MM", "screen_mins": int}}`
- Consumed by: Task 4 (`client.py`)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_parsers.py
from familylink.parsers import parse_apps_and_usage, parse_members_response, parse_time_limit


def test_parse_members_response_extracts_user_id():
    raw = [
        [
            [
                "child1", None, 3,
                ["Alice", None, "", "alice@g.com", "Smith", "Alice", None, None, ""],
                "1", None, None, None, None, None, None, [True, False],
            ]
        ],
        [None, "99999"],
        "parent_id",
    ]
    result = parse_members_response(raw)
    assert result["myUserId"] == "parent_id"
    assert result["members"][0]["userId"] == "child1"
    assert result["members"][0]["profile"]["displayName"] == "Alice"
    assert result["members"][0]["role"] == "member"


def test_parse_members_response_empty():
    result = parse_members_response([[], [None, "0"], "p1"])
    assert result["members"] == []
    assert result["myUserId"] == "p1"


def test_parse_apps_and_usage_empty_lists():
    raw = [[None, "1"], [], "0", [], None, None, []]
    result = parse_apps_and_usage(raw)
    assert result["apps"] == []
    assert result["deviceInfo"] == []
    assert result["appUsageSessions"] == []


def test_parse_time_limit_empty_returns_empty_dict():
    result = parse_time_limit([])
    assert result == {}


def test_parse_time_limit_has_day_keys_as_ints():
    # Minimal structure: one downtime entry for day 1 (Monday)
    raw = [
        None,
        [
            [None, [[None, 1, None, [21, 0], [7, 0]]]],  # downtime block
            [[[None, None, [[None, 1, None, 120]]]]],     # screen time block
        ],
    ]
    result = parse_time_limit(raw)
    assert 1 in result
    assert result[1]["avail_start"] == "07:00"
    assert result[1]["avail_end"] == "21:00"
    assert result[1]["screen_mins"] == 120
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/unit/test_parsers.py -v
```

Expected: `ImportError: cannot import name 'parse_members_response' from 'familylink.parsers'`

- [ ] **Step 3: Create parsers.py**

Create `src/familylink/parsers.py`. Copy the three static methods from `client.py`, rename them (drop the leading underscore and `_parse_` prefix → `parse_`), and make them module-level functions:

```python
"""Protobuf-JSON response parsers for the Family Link API."""


def parse_members_response(data: list) -> dict:
    """Convert /families/mine/members positional list to a MembersResponse-compatible dict."""
    _ROLE_NAMES = {1: "familyManager", 2: "parent", 3: "member", 4: "child"}
    members = []
    for m in (data[0] or []):
        pl = m[3] if len(m) > 3 and m[3] else []
        birthday = None
        if len(pl) > 7 and pl[7] and isinstance(pl[7], list):
            b = pl[7]
            birthday = {"day": b[0], "month": b[1], "year": b[2]}
        sup = m[7] if len(m) > 7 and m[7] and isinstance(m[7], list) else None
        supervision_info = None
        if sup:
            supervision_info = {
                "isSupervisedMember": bool(sup[0]),
                "isGuardianLinkedAccount": bool(sup[1]) if len(sup) > 1 else False,
            }
        role_int = m[2] if len(m) > 2 else 0
        members.append({
            "userId": m[0],
            "role": _ROLE_NAMES.get(role_int, str(role_int)),
            "profile": {
                "displayName": pl[0] if len(pl) > 0 else "",
                "profileImageUrl": pl[2] if len(pl) > 2 else "",
                "email": pl[3] if len(pl) > 3 else "",
                "familyName": pl[4] or "" if len(pl) > 4 else "",
                "givenName": pl[5] or "" if len(pl) > 5 else "",
                "defaultProfileImageUrl": pl[8] if len(pl) > 8 else "",
                "birthday": birthday,
            },
            "state": str(m[4]) if len(m) > 4 else "1",
            "memberSupervisionInfo": supervision_info,
        })
    hdr = data[1] if len(data) > 1 and data[1] else [None, "0"]
    return {
        "members": members,
        "apiHeader": {"serverTimestampMillis": hdr[1] if len(hdr) > 1 else "0"},
        "myUserId": str(data[2]) if len(data) > 2 else "",
    }


def parse_apps_and_usage(data: list) -> dict:
    """Convert /appsandusage positional list to an AppUsage-compatible dict."""
    _SOURCE = {1: "unknownAppSource", 2: "googlePlay"}
    _CAP = {1: "capabilityAlwaysAllowApp", 2: "capabilityBlock", 3: "capabilityUsageLimit"}

    def _supervision(sup: list) -> dict:
        if not isinstance(sup, list) or not sup:
            return {"hidden": False, "hiddenSetExplicitly": False}
        usage_limit = None
        raw_lim = sup[4] if len(sup) > 4 else None
        if isinstance(raw_lim, list) and len(raw_lim) >= 2:
            usage_limit = {"dailyUsageLimitMins": raw_lim[0], "enabled": bool(raw_lim[1])}
        aa2 = sup[2] if len(sup) > 2 else None
        aa5 = sup[5] if len(sup) > 5 else None
        always_allowed = None
        if aa2 == 1 or (isinstance(aa5, list) and aa5 and aa5[0] == 1):
            always_allowed = {"alwaysAllowedState": "alwaysAllowedStateEnabled"}
        return {
            "hidden": bool(sup[0]),
            "hiddenSetExplicitly": bool(sup[1]) if len(sup) > 1 else False,
            "usageLimit": usage_limit,
            "alwaysAllowedAppInfo": always_allowed,
        }

    apps = []
    for a in (data[1] or []):
        caps_raw = a[9] if len(a) > 9 and isinstance(a[9], list) else []
        apps.append({
            "packageName": a[0],
            "title": a[1],
            "iconUrl": a[2] if len(a) > 2 else "",
            "supervisionSetting": _supervision(a[3] if len(a) > 3 else []),
            "installTimeMillis": a[4] if len(a) > 4 else "0",
            "enforcedEnabledStatus": str(a[12]) if len(a) > 12 else "1",
            "appSource": _SOURCE.get(a[10] if len(a) > 10 else 1, "unknownAppSource"),
            "supervisionCapabilities": [_CAP[c] for c in caps_raw if c in _CAP],
            "adSupportStatus": "noAds",
            "iapSupportStatus": "noIap",
            "deviceIds": a[11] if len(a) > 11 and isinstance(a[11], list) else [],
        })

    device_info = []
    for d in (data[3] or []):
        di = d[1] if len(d) > 1 and isinstance(d[1], list) else []
        caps_raw = d[2][0] if len(d) > 2 and isinstance(d[2], list) and d[2] else []
        device_info.append({
            "deviceId": d[0],
            "displayInfo": {
                "model": di[2] if len(di) > 2 and di[2] else "",
                "friendlyName": di[3] if len(di) > 3 and di[3] else (di[2] or ""),
                "lastActivityTimeMillis": di[6] if len(di) > 6 and di[6] else "0",
            },
            "capabilityInfo": {
                "capabilities": [str(c) for c in (caps_raw if isinstance(caps_raw, list) else [])],
            },
        })

    sessions = []
    for s in (data[6] or []):
        dur = s[0] if len(s) > 0 and isinstance(s[0], list) else ["0", 0]
        pkg = s[1][0] if len(s) > 1 and isinstance(s[1], list) and s[1] else ""
        date_raw = s[4] if len(s) > 4 and isinstance(s[4], list) else [2000, 1, 1]
        nanos = dur[1] if len(dur) > 1 else 0
        sessions.append({
            "usage": f"{dur[0]}.{nanos // 1000000:03d}",
            "appId": {"androidAppPackageName": pkg},
            "deviceMudId": s[2] if len(s) > 2 else "",
            "modeType": str(s[3]) if len(s) > 3 else "0",
            "date": {"year": date_raw[0], "month": date_raw[1], "day": date_raw[2]},
        })

    hdr = data[0] if len(data) > 0 and isinstance(data[0], list) else [None, "0"]
    return {
        "apiHeader": {"serverTimestampMillis": hdr[1] if len(hdr) > 1 else "0"},
        "apps": apps,
        "lastActivityRefreshTimestampMillis": str(data[2]) if len(data) > 2 else "0",
        "deviceInfo": device_info,
        "appUsageSessions": sessions,
    }


def parse_time_limit(data: list) -> dict[int, dict]:
    """Parse /timeLimit positional list response.

    Returns {day_int: {"avail_start": "HH:MM", "avail_end": "HH:MM", "screen_mins": int}}
    where day_int 1=Mon … 7=Sun. avail_start/end is the device-on window (inverse of downtime).
    """
    result: dict[int, dict] = {}
    schedules = data[1] if len(data) > 1 and isinstance(data[1], list) else []

    dt_block = schedules[0] if schedules else []
    per_day_dt = dt_block[1] if len(dt_block) > 1 and isinstance(dt_block[1], list) else []
    for e in per_day_dt:
        if not isinstance(e, list) or len(e) < 5:
            continue
        day = e[1]
        bedtime_start = e[3] if isinstance(e[3], list) else [0, 0]
        wake_time = e[4] if isinstance(e[4], list) else [0, 0]
        result.setdefault(day, {})
        result[day]["avail_start"] = f"{wake_time[0]:02d}:{wake_time[1] if len(wake_time) > 1 else 0:02d}"
        result[day]["avail_end"] = f"{bedtime_start[0]:02d}:{bedtime_start[1] if len(bedtime_start) > 1 else 0:02d}"

    sc_outer = schedules[1] if len(schedules) > 1 and isinstance(schedules[1], list) else []
    sc_inner = sc_outer[0] if sc_outer and isinstance(sc_outer[0], list) else []
    per_day_sc = sc_inner[2] if len(sc_inner) > 2 and isinstance(sc_inner[2], list) else []
    for e in per_day_sc:
        if not isinstance(e, list) or len(e) < 4:
            continue
        result.setdefault(e[1], {})
        result[e[1]]["screen_mins"] = e[3]

    return result
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
pytest tests/unit/test_parsers.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink/parsers.py tests/unit/test_parsers.py
git commit -m "feat: extract API response parsers to parsers.py"
```

---

### Task 3: Extract CookieResolver to auth.py

**Files:**
- Create: `src/familylink/auth.py`
- Create/Modify: `tests/unit/test_auth.py`

**Interfaces:**
- Produces: `CookieResolver(browser, cookie_file_path).resolve() -> tuple[str, CookieJar | None]`
  - Returns `(sapisid_string, cookie_jar_or_None)`
  - Raises `ValueError` if cookie file missing or SAPISID not found
  - Raises `RuntimeError` if no browser_cookie3 and no other source available
- Consumed by: Task 4 (`FamilyLink.__init__`)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_auth.py
import base64

import pytest

from familylink.auth import CookieResolver

MINIMAL_COOKIES = (
    "# Netscape HTTP Cookie File\n"
    ".google.com\tTRUE\t/\tTRUE\t9999999999\tSAPISID\tmy_sapisid_value\n"
    ".google.com\tTRUE\t/\tTRUE\t9999999999\tSID\tsid_value\n"
)


def test_resolve_from_b64_env(monkeypatch):
    encoded = base64.b64encode(MINIMAL_COOKIES.encode()).decode()
    monkeypatch.setenv("FAMILYLINK_COOKIES_B64", encoded)
    monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
    monkeypatch.delenv("FAMILYLINK_COOKIE_FILE", raising=False)
    sapisid, jar = CookieResolver().resolve()
    assert sapisid == "my_sapisid_value"
    assert jar is not None


def test_resolve_from_sapisid_env(monkeypatch):
    monkeypatch.delenv("FAMILYLINK_COOKIES_B64", raising=False)
    monkeypatch.setenv("FAMILYLINK_SAPISID", "env_sapisid")
    monkeypatch.delenv("FAMILYLINK_COOKIE_FILE", raising=False)
    sapisid, jar = CookieResolver().resolve()
    assert sapisid == "env_sapisid"
    assert jar is None


def test_resolve_from_cookie_file(monkeypatch, tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(MINIMAL_COOKIES)
    monkeypatch.delenv("FAMILYLINK_COOKIES_B64", raising=False)
    monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
    monkeypatch.delenv("FAMILYLINK_COOKIE_FILE", raising=False)
    monkeypatch.delenv("FAMILYLINK_PROFILES_DIR", raising=False)
    sapisid, jar = CookieResolver(browser="txt", cookie_file_path=cookie_file).resolve()
    assert sapisid == "my_sapisid_value"
    assert jar is not None


def test_resolve_raises_when_txt_browser_file_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("FAMILYLINK_COOKIES_B64", raising=False)
    monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
    monkeypatch.delenv("FAMILYLINK_COOKIE_FILE", raising=False)
    monkeypatch.delenv("FAMILYLINK_PROFILES_DIR", raising=False)
    with pytest.raises(ValueError, match="Cookie file not found"):
        CookieResolver(browser="txt", cookie_file_path=tmp_path / "missing.txt").resolve()


def test_resolve_raises_when_no_source_available(monkeypatch):
    monkeypatch.delenv("FAMILYLINK_COOKIES_B64", raising=False)
    monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
    monkeypatch.delenv("FAMILYLINK_COOKIE_FILE", raising=False)
    monkeypatch.delenv("FAMILYLINK_PROFILES_DIR", raising=False)
    # Patch browser_cookie3 to None so the last resort is unavailable
    import familylink.auth as auth_mod
    monkeypatch.setattr(auth_mod, "browser_cookie3", None)
    with pytest.raises(RuntimeError):
        CookieResolver(browser="txt").resolve()
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
pytest tests/unit/test_auth.py -v
```

Expected: `ImportError: cannot import name 'CookieResolver' from 'familylink.auth'`

- [ ] **Step 3: Create auth.py**

Extract the auth block verbatim from `FamilyLink.__init__` into a new class. Create `src/familylink/auth.py`:

```python
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
            p = Path(self._cookie_file_path) if self._cookie_file_path else Path("./cookies.txt")
            if not p.exists() or not p.is_file():
                raise ValueError(f"Cookie file not found: {p}")
            cj = MozillaCookieJar()
            cj.load(str(p.resolve()), ignore_discard=True, ignore_expires=True)
            cookies_jar = cj

        if not cookies_jar and in_profiles_dir and not sapisid and self._browser != "txt":
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
                cj.load(str(self._cookie_file_path.resolve()), ignore_discard=True, ignore_expires=True)
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
                raise RuntimeError("browser_cookie3 not available and no cached session found")
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
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
pytest tests/unit/test_auth.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink/auth.py tests/unit/test_auth.py
git commit -m "feat: extract CookieResolver to auth.py"
```

---

### Task 4: Slim down client.py

**Files:**
- Modify: `src/familylink/client.py`
- Create/Modify: `tests/unit/test_client.py`

**Interfaces:**
- Consumes:
  - `CookieResolver(browser, cookie_file_path).resolve() -> tuple[str, CookieJar | None]` (from Task 3)
  - `parsers.parse_members_response(list) -> dict` (from Task 2)
  - `parsers.parse_apps_and_usage(list) -> dict` (from Task 2)
  - `MembersResponse.model_validate(dict)`, `AppUsage.model_validate(dict)` (from Task 1)
- Produces: unchanged public API — `FamilyLink(account_id, browser, cookie_file_path)` with all existing methods

- [ ] **Step 1: Recover deleted test file**

```bash
git show efc4cc7:tests/unit/test_client.py > tests/unit/test_client.py
```

If the file doesn't exist at that commit, create `tests/unit/test_client.py` with:

```python
# tests/unit/test_client.py
import pytest
from familylink import FamilyLink, SessionExpiredError

MINIMAL_COOKIES = (
    "# Netscape HTTP Cookie File\n"
    ".google.com\tTRUE\t/\tTRUE\t9999999999\tSAPISID\ttest_sapisid\n"
    ".google.com\tTRUE\t/\tTRUE\t9999999999\tSID\tsid_value\n"
)

BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"


@pytest.fixture
def client(monkeypatch, tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(MINIMAL_COOKIES)
    monkeypatch.delenv("FAMILYLINK_COOKIES_B64", raising=False)
    monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
    return FamilyLink(browser="txt", cookie_file_path=cookie_file)


def test_get_members_parses_list_response(client, httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/families/mine/members",
        json=[
            [
                [
                    "child1", None, 3,
                    ["Alice", None, "", "alice@g.com", "Smith", "Alice", None, None, ""],
                    "1", None, None, None, None, None, None, [True, False],
                ]
            ],
            [None, "12345"],
            "parent1",
        ],
    )
    result = client.get_members()
    assert result.my_user_id == "parent1"
    assert result.members[0].user_id == "child1"
    assert result.members[0].profile.display_name == "Alice"


def test_get_members_raises_on_401(client, httpx_mock):
    httpx_mock.add_response(url=f"{BASE}/families/mine/members", status_code=401)
    with pytest.raises(SessionExpiredError):
        client.get_members()


def test_get_members_raises_on_403(client, httpx_mock):
    httpx_mock.add_response(url=f"{BASE}/families/mine/members", status_code=403)
    with pytest.raises(SessionExpiredError):
        client.get_members()
```

- [ ] **Step 2: Run current tests — note failures**

```bash
pytest tests/unit/test_client.py -v
```

This establishes the baseline. Note any errors.

- [ ] **Step 3: Rewrite client.py**

Replace `src/familylink/client.py` in full:

```python
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
    ts = int(time.time() * 1000)
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
        self._session = httpx.Client(headers=self._headers, cookies=self._cookies, timeout=30)

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
            if mem.member_supervision_info and mem.member_supervision_info.is_supervised_member:
                return mem.user_id
        raise ValueError("No supervised account found; set account_id explicitly")

    # ── Read API ──────────────────────────────────────────────────────────────

    def get_members(self) -> MembersResponse:
        data = self._get("/families/mine/members").json()
        if isinstance(data, list):
            data = parsers.parse_members_response(data)
        return MembersResponse.model_validate(data)

    def get_apps_and_usage(self, child_id: str) -> AppUsage:
        params = [
            ("capabilities", "CAPABILITY_APP_USAGE_SESSION"),
            ("capabilities", "CAPABILITY_SUPERVISION_CAPABILITIES"),
        ]
        data = self._get(f"/people/{child_id}/appsandusage", params).json()
        if isinstance(data, list):
            data = parsers.parse_apps_and_usage(data)
        return AppUsage.model_validate(data)

    def get_time_limit(self, child_id: str) -> dict:
        return self._get(f"/people/{child_id}/timeLimit").json()

    def get_applied_time_limits(self, child_id: str) -> dict:
        return self._get(f"/people/{child_id}/appliedTimeLimits").json()

    def get_time_limits(self, account_id: str | None = None) -> dict:
        aid = account_id or self._ensure_account_id()
        return self._session.get(
            f"{self.BASE_URL}/people/{aid}/appliedTimeLimits",
            headers={"Content-Type": "application/json"},
        ).json()

    def print_usage(self) -> None:
        for m in self.get_members().members:
            p = m.profile
            print(f"- {p.display_name} | {p.email} | user_id={m.user_id}")

    # ── Device operations ─────────────────────────────────────────────────────

    def set_time_limits_device(
        self, account_id: str | None = None, device_id: str = "",
        period_id: str = "", time_in_minutes: int = 0,
    ) -> dict:
        aid = account_id or self._ensure_account_id()
        payload = json.dumps(
            [None, aid, [[None, None, 8, device_id, None, None, None, None, None, None, None,
                          [2, time_in_minutes, period_id]]], [1]]
        )
        return self._post(f"/people/{aid}/timeLimitOverrides:batchCreate", payload).json()

    def disable_time_limits_device(
        self, account_id: str | None = None, device_id: str = "",
        period_id: str = "", time_in_minutes: int = 0,
    ) -> dict:
        aid = account_id or self._ensure_account_id()
        payload = json.dumps(
            [None, aid, [[None, None, 8, device_id, None, None, None, None, None, None, None,
                          [1, time_in_minutes, period_id]]], [1]]
        )
        return self._post(f"/people/{aid}/timeLimitOverrides:batchCreate", payload).json()

    def enable_time_limits_device(
        self, account_id: str | None = None, device_id: str = "",
        period_id: str = "", time_in_minutes: int = 0,
    ) -> dict:
        return self.set_time_limits_device(account_id, device_id, period_id, time_in_minutes)

    def lock_device(self, account_id: str | None = None, device_id: str = "") -> dict:
        aid = account_id or self._ensure_account_id()
        return self._post(
            f"/people/{aid}/timeLimitOverrides:batchCreate",
            json.dumps([None, aid, [[None, None, 1, device_id]], [1]]),
        ).json()

    def unlock_device(self, account_id: str | None = None, device_id: str = "") -> dict:
        aid = account_id or self._ensure_account_id()
        return self._post(
            f"/people/{aid}/timeLimitOverrides:batchCreate",
            json.dumps([None, aid, [[None, None, 4, device_id]], [1]]),
        ).json()

    def enable_downtime_device(
        self, account_id: str | None = None, device_id: str = "",
        start_hour: int = 0, start_minute: int = 0,
        end_hour: int = 0, end_minute: int = 0, period_id: str = "",
    ) -> dict:
        aid = account_id or self._ensure_account_id()
        payload = json.dumps(
            [None, aid, [[None, None, 9, None, None, None, None, None, None, None, None, None,
                          [2, [start_hour, start_minute], [end_hour, end_minute], period_id]]], [1]]
        )
        return self._post(f"/people/{aid}/timeLimitOverrides:batchCreate", payload).json()

    def disable_downtime_device(
        self, account_id: str | None = None, device_id: str = "",
        start_hour: int = 0, start_minute: int = 0,
        end_hour: int = 0, end_minute: int = 0, period_id: str = "",
    ) -> dict:
        aid = account_id or self._ensure_account_id()
        payload = json.dumps(
            [None, aid, [[None, None, 9, None, None, None, None, None, None, None, None, None,
                          [1, [start_hour, start_minute], [end_hour, end_minute], period_id]]], [1]]
        )
        return self._post(f"/people/{aid}/timeLimitOverrides:batchCreate", payload).json()
```

- [ ] **Step 4: Run all unit tests**

```bash
pytest tests/unit/ -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink/client.py tests/unit/test_client.py
git commit -m "refactor: slim client.py — delegate to auth.py and parsers.py"
```

---

### Task 5: Discover and implement missing app management methods

**Context:** `cli.py` calls `client.set_app_limit(title, mins)`, `client.block_app(title)`, `client.always_allow_app(title)` — none exist yet. These write to the app supervision API. The endpoint and payload must be discovered by network inspection.

**Files:**
- Modify: `src/familylink/client.py` (add 4 methods)
- Modify: `src/familylink/cli.py` (pass `package_name` instead of `title`)
- Modify: `tests/unit/test_client.py` (add tests for 4 methods)

**Interfaces:**
- Produces:
  - `FamilyLink.set_app_limit(package_name: str, minutes: int, child_id: str | None = None) -> dict`
  - `FamilyLink.block_app(package_name: str, child_id: str | None = None) -> dict`
  - `FamilyLink.always_allow_app(package_name: str, child_id: str | None = None) -> dict`
  - `FamilyLink.remove_app_limit(package_name: str, child_id: str | None = None) -> dict`

- [ ] **Step 1: Discover the API endpoint via network inspection**

Open https://familylink.google.com in Chrome. Open DevTools → Network tab → filter `Fetch/XHR`. Manually change an app's limit (e.g. set YouTube to 30 min). In the network panel, find the POST request that fires. Record:

1. The URL path (everything after `/kidsmanagement/v1`)
2. The request body (copy as JSON)
3. Repeat for block, always-allow, remove-limit actions

Also check git history for any hints from removed test files:

```bash
git log --all --oneline -- tests/unit/test_client.py
# Then for each hash shown:
git show <hash>:tests/unit/test_client.py 2>/dev/null | grep -A 30 "block_app\|set_app_limit\|always_allow"
```

- [ ] **Step 2: Write failing tests with discovered endpoint**

Add to `tests/unit/test_client.py` (substitute `<PATH>` and `<PAYLOAD_ASSERT>` from Step 1):

```python
def test_set_app_limit_posts_to_correct_endpoint(client, httpx_mock):
    httpx_mock.add_response(method="POST", url__regex=r".*kidsmanagement.*", json={})
    client.set_app_limit("com.google.android.youtube", 30, child_id="child1")
    request = httpx_mock.get_requests()[-1]
    assert "/people/child1/" in str(request.url)
    import json
    body = json.loads(request.content)
    # Assert body contains package name and 30 minutes — exact shape from Step 1
    assert "com.google.android.youtube" in str(body)


def test_block_app_posts_to_correct_endpoint(client, httpx_mock):
    httpx_mock.add_response(method="POST", url__regex=r".*kidsmanagement.*", json={})
    client.block_app("com.google.android.youtube", child_id="child1")
    request = httpx_mock.get_requests()[-1]
    assert "/people/child1/" in str(request.url)


def test_always_allow_app(client, httpx_mock):
    httpx_mock.add_response(method="POST", url__regex=r".*kidsmanagement.*", json={})
    client.always_allow_app("com.google.android.youtube", child_id="child1")
    request = httpx_mock.get_requests()[-1]
    assert "/people/child1/" in str(request.url)


def test_remove_app_limit(client, httpx_mock):
    httpx_mock.add_response(method="POST", url__regex=r".*kidsmanagement.*", json={})
    client.remove_app_limit("com.google.android.youtube", child_id="child1")
    request = httpx_mock.get_requests()[-1]
    assert "/people/child1/" in str(request.url)
```

- [ ] **Step 3: Run tests — confirm they fail**

```bash
pytest tests/unit/test_client.py -k "set_app_limit or block_app or always_allow or remove_app" -v
```

Expected: `AttributeError: 'FamilyLink' object has no attribute 'set_app_limit'`

- [ ] **Step 4: Add the 4 methods to client.py**

Add inside the `FamilyLink` class, under a `# ── App supervision ──` comment. Use the endpoint and payload shape from Step 1 discovery. Pattern follows the existing device methods:

```python
# ── App supervision ───────────────────────────────────────────────────────────

def set_app_limit(
    self,
    package_name: str,
    minutes: int,
    child_id: str | None = None,
) -> dict:
    """Set a daily time limit (minutes) on an app."""
    aid = child_id or self._ensure_account_id()
    # Payload shape confirmed by network inspection — fill in from Step 1
    payload = json.dumps([...])
    return self._post(f"/people/{aid}/<DISCOVERED_PATH>", payload).json()

def block_app(self, package_name: str, child_id: str | None = None) -> dict:
    """Block an app (hidden from child)."""
    aid = child_id or self._ensure_account_id()
    payload = json.dumps([...])
    return self._post(f"/people/{aid}/<DISCOVERED_PATH>", payload).json()

def always_allow_app(self, package_name: str, child_id: str | None = None) -> dict:
    """Set an app to always allowed (no daily limit)."""
    aid = child_id or self._ensure_account_id()
    payload = json.dumps([...])
    return self._post(f"/people/{aid}/<DISCOVERED_PATH>", payload).json()

def remove_app_limit(self, package_name: str, child_id: str | None = None) -> dict:
    """Remove any daily time limit from an app (returns it to blocked)."""
    aid = child_id or self._ensure_account_id()
    payload = json.dumps([...])
    return self._post(f"/people/{aid}/<DISCOVERED_PATH>", payload).json()
```

- [ ] **Step 5: Update cli.py `_apply_config` to pass package_name**

In `src/familylink/cli.py`, inside `_apply_config`, build a title→package_name mapping from the already-fetched `app_usage`:

```python
# Add this line after: app_usage = client.get_apps_and_usage(child_id)
pkg_by_title = {app.title: app.package_name for app in app_usage.apps}

# Replace the three call sites:
# BEFORE:  client.always_allow_app(app)
# AFTER:
if pkg := pkg_by_title.get(app):
    client.always_allow_app(pkg, child_id)

# BEFORE:  client.set_app_limit(app, expected_limit)
# AFTER:
if pkg := pkg_by_title.get(app):
    client.set_app_limit(pkg, expected_limit, child_id)

# BEFORE:  client.block_app(app)
# AFTER:
if pkg := pkg_by_title.get(app):
    client.block_app(pkg, child_id)
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/familylink/client.py src/familylink/cli.py tests/unit/test_client.py
git commit -m "feat: add set_app_limit, block_app, always_allow_app, remove_app_limit"
```
