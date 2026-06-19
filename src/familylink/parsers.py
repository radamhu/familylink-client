"""Protobuf-JSON response parsers for the Family Link API."""


def parse_members_response(data: list) -> dict:
    """Convert /families/mine/members positional list to a MembersResponse-compatible dict."""
    _ROLE_NAMES = {1: "familyManager", 2: "parent", 3: "member", 4: "child"}
    members = []
    for m in data[0] or []:
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
        members.append(
            {
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
            }
        )
    hdr = data[1] if len(data) > 1 and data[1] else [None, "0"]
    return {
        "members": members,
        "apiHeader": {"serverTimestampMillis": hdr[1] if len(hdr) > 1 else "0"},
        "myUserId": str(data[2]) if len(data) > 2 else "",
    }


def parse_apps_and_usage(data: list) -> dict:
    """Convert /appsandusage positional list to an AppUsage-compatible dict."""
    _SOURCE = {1: "unknownAppSource", 2: "googlePlay"}
    _CAP = {
        1: "capabilityAlwaysAllowApp",
        2: "capabilityBlock",
        3: "capabilityUsageLimit",
    }

    def _supervision(sup: list) -> dict:
        if not isinstance(sup, list) or not sup:
            return {"hidden": False, "hiddenSetExplicitly": False}
        usage_limit = None
        raw_lim = sup[4] if len(sup) > 4 else None
        if isinstance(raw_lim, list) and len(raw_lim) >= 2:
            usage_limit = {
                "dailyUsageLimitMins": raw_lim[0],
                "enabled": bool(raw_lim[1]),
            }
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
    for a in data[1] or []:
        caps_raw = a[9] if len(a) > 9 and isinstance(a[9], list) else []
        apps.append(
            {
                "packageName": a[0],
                "title": a[1],
                "iconUrl": a[2] if len(a) > 2 else "",
                "supervisionSetting": _supervision(a[3] if len(a) > 3 else []),
                "installTimeMillis": a[4] if len(a) > 4 else "0",
                "enforcedEnabledStatus": str(a[12]) if len(a) > 12 else "1",
                "appSource": _SOURCE.get(
                    a[10] if len(a) > 10 else 1, "unknownAppSource"
                ),
                "supervisionCapabilities": [_CAP[c] for c in caps_raw if c in _CAP],
                "adSupportStatus": "noAds",
                "iapSupportStatus": "noIap",
                "deviceIds": a[11] if len(a) > 11 and isinstance(a[11], list) else [],
            }
        )

    device_info = []
    for d in data[3] or []:
        di = d[1] if len(d) > 1 and isinstance(d[1], list) else []
        caps_raw = d[2][0] if len(d) > 2 and isinstance(d[2], list) and d[2] else []
        device_info.append(
            {
                "deviceId": d[0],
                "displayInfo": {
                    "model": di[2] if len(di) > 2 and di[2] else "",
                    "friendlyName": di[3] if len(di) > 3 and di[3] else (di[2] or ""),
                    "lastActivityTimeMillis": di[6] if len(di) > 6 and di[6] else "0",
                },
                "capabilityInfo": {
                    "capabilities": [
                        str(c) for c in (caps_raw if isinstance(caps_raw, list) else [])
                    ],
                },
            }
        )

    sessions = []
    for s in data[6] or []:
        dur = s[0] if len(s) > 0 and isinstance(s[0], list) else ["0", 0]
        pkg = s[1][0] if len(s) > 1 and isinstance(s[1], list) and s[1] else ""
        date_raw = s[4] if len(s) > 4 and isinstance(s[4], list) else [2000, 1, 1]
        nanos = dur[1] if len(dur) > 1 else 0
        sessions.append(
            {
                "usage": f"{dur[0]}.{nanos // 1000000:03d}",
                "appId": {"androidAppPackageName": pkg},
                "deviceMudId": s[2] if len(s) > 2 else "",
                "modeType": str(s[3]) if len(s) > 3 else "0",
                "date": {"year": date_raw[0], "month": date_raw[1], "day": date_raw[2]},
            }
        )

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
    per_day_dt = (
        dt_block[1] if len(dt_block) > 1 and isinstance(dt_block[1], list) else []
    )
    for e in per_day_dt:
        if not isinstance(e, list) or len(e) < 5:
            continue
        day = e[1]
        bedtime_start = e[3] if isinstance(e[3], list) else [0, 0]
        wake_time = e[4] if isinstance(e[4], list) else [0, 0]
        result.setdefault(day, {})
        result[day]["avail_start"] = (
            f"{wake_time[0]:02d}:{wake_time[1] if len(wake_time) > 1 else 0:02d}"
        )
        result[day]["avail_end"] = (
            f"{bedtime_start[0]:02d}:{bedtime_start[1] if len(bedtime_start) > 1 else 0:02d}"
        )

    sc_outer = (
        schedules[1] if len(schedules) > 1 and isinstance(schedules[1], list) else []
    )
    sc_inner = sc_outer[0] if sc_outer and isinstance(sc_outer[0], list) else []
    per_day_sc = (
        sc_inner[2] if len(sc_inner) > 2 and isinstance(sc_inner[2], list) else []
    )
    for e in per_day_sc:
        if not isinstance(e, list) or len(e) < 4:
            continue
        result.setdefault(e[1], {})
        result[e[1]]["screen_mins"] = e[3]

    return result
