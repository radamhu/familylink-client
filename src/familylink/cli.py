"""Family Link CLI"""

import argparse
import base64
import csv
import logging
import os
import sys
from datetime import datetime
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import httpx
from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

from familylink import FamilyLink, SessionExpiredError, parsers
from familylink.models import AlwaysAllowedState

try:
    import browser_cookie3
except Exception:
    browser_cookie3 = None

# Configure rich console with custom theme
console = Console(
    theme=Theme(
        {
            "info": "cyan",
            "warning": "yellow",
            "error": "red bold",
            "success": "green",
        }
    )
)

# Configure logging with rich handler
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        RichHandler(
            console=console,
            show_time=False,
            show_path=False,
            rich_tracebacks=True,
            tracebacks_show_locals=True,
        )
    ],
)
# Set httpx logging to WARNING by default to hide request logs
logging.getLogger("httpx").setLevel(logging.WARNING)
_logger = logging.getLogger(__name__)


def _push_to_coolify(
    base64_value: str, url: str, token: str, app_uuid: str, *, restart: bool
) -> None:
    """Push FAMILYLINK_COOKIES_B64 to Coolify and optionally restart the app."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.patch(
            f"{url}/api/v1/applications/{app_uuid}/envs",
            headers=headers,
            json={
                "key": "FAMILYLINK_COOKIES_B64",
                "value": base64_value,
                "is_preview": False,
            },
        )
    except httpx.RequestError as exc:
        console.print(f"[error]Coolify network error:[/error] {exc}")
        sys.exit(1)
    if not resp.is_success:
        console.print(
            f"[error]Coolify API error {resp.status_code}:[/error] {resp.text}"
        )
        sys.exit(1)
    console.print("[success]Updated FAMILYLINK_COOKIES_B64 in Coolify[/success]")

    if restart:
        try:
            resp = httpx.get(
                f"{url}/api/v1/applications/{app_uuid}/restart",
                headers=headers,
            )
        except httpx.RequestError as exc:
            console.print(f"[error]Coolify restart network error:[/error] {exc}")
            sys.exit(1)
        if not resp.is_success:
            console.print(
                f"[error]Coolify restart error {resp.status_code}:[/error] {resp.text}"
            )
            sys.exit(1)
        console.print("[success]Restarted familylink-client in Coolify[/success]")


def _cmd_export_cookies(argv: list[str]) -> None:
    """Export Google cookies for cloud/Docker deployment."""
    parser = argparse.ArgumentParser(
        prog="familylink export-cookies",
        description=(
            "Export Google cookies from your local browser to a file or base64 string "
            "for use with FAMILYLINK_COOKIES_B64 or FAMILYLINK_COOKIE_FILE."
        ),
    )
    parser.add_argument(
        "--browser",
        choices=["firefox", "chrome"],
        default="firefox",
        help="Browser to extract cookies from (default: firefox)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="cookies.txt",
        help="Output file path (default: cookies.txt)",
    )
    parser.add_argument(
        "--base64",
        action="store_true",
        help="Also print the base64-encoded value for FAMILYLINK_COOKIES_B64",
    )
    parser.add_argument(
        "--coolify",
        action="store_true",
        help="Push FAMILYLINK_COOKIES_B64 to the Coolify app after updating .env. Requires --base64.",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Restart the Coolify app after pushing the env var. Requires --coolify.",
    )
    args = parser.parse_args(argv)

    if args.coolify and not args.base64:
        console.print("[error]--coolify requires --base64[/error]")
        sys.exit(1)
    if args.restart and not args.coolify:
        console.print("[error]--restart requires --coolify[/error]")
        sys.exit(1)

    coolify_url = coolify_token = coolify_app_uuid = None
    if args.coolify:
        coolify_url = os.environ.get("COOLIFY_URL")
        coolify_token = os.environ.get("COOLIFY_TOKEN")
        coolify_app_uuid = os.environ.get("COOLIFY_APP_UUID")
        for name, val in [
            ("COOLIFY_URL", coolify_url),
            ("COOLIFY_TOKEN", coolify_token),
            ("COOLIFY_APP_UUID", coolify_app_uuid),
        ]:
            if not val:
                console.print(f"[error]{name} is not set.[/error]")
                sys.exit(1)

    if browser_cookie3 is None:
        console.print(
            "[error]browser_cookie3 is not installed.[/error]\n"
            "Run: [bold]pip install browser-cookie3[/bold]  (host only — not needed in Docker)"
        )
        sys.exit(1)

    console.print(f"Extracting Google cookies from [bold]{args.browser}[/bold]...")
    source_jar = getattr(browser_cookie3, args.browser)()

    out_jar = MozillaCookieJar()
    for cookie in source_jar:
        if "google.com" in cookie.domain:
            out_jar.set_cookie(cookie)

    sapisid_found = any(c.name == "SAPISID" for c in out_jar)
    if not sapisid_found:
        console.print(
            "[error]SAPISID cookie not found.[/error] "
            "Sign in to [bold]https://familylink.google.com[/bold] in your browser first."
        )
        sys.exit(1)

    out_jar.save(args.output, ignore_discard=True, ignore_expires=True)
    console.print(f"[success]Cookies saved to {args.output}[/success]")

    if args.base64:
        content = Path(args.output).read_bytes()
        encoded = base64.b64encode(content).decode()
        console.print(
            "\n[bold]For cloud/Docker — store this value as a secret and inject as:[/bold]\n"
            f"  [cyan]export FAMILYLINK_COOKIES_B64={encoded}[/cyan]\n\n"
            "[dim]Re-run this command when Google invalidates the session (sign-out, password change).[/dim]"
        )

        env_path = Path(".env")
        line = f"FAMILYLINK_COOKIES_B64={encoded}"
        if env_path.exists():
            lines = env_path.read_text().splitlines()
            found = False
            for i, ln in enumerate(lines):
                if ln.strip().startswith("FAMILYLINK_COOKIES_B64"):
                    lines[i] = line
                    found = True
                    break
            if not found:
                lines.append(line)
            env_path.write_text("\n".join(lines) + "\n")
        else:
            env_path.write_text(line + "\n")
        console.print(f"[success]Updated {env_path}[/success]")

        if args.coolify:
            _push_to_coolify(
                encoded,
                coolify_url,
                coolify_token,
                coolify_app_uuid,
                restart=args.restart,
            )


def _mins_to_hhmm(mins: int) -> str:
    return f"{mins // 60}:{mins % 60:02d}"


def _cmd_fetch_config(argv: list[str]) -> None:
    """Fetch current Family Link supervision settings and write config CSV file(s)."""
    parser = argparse.ArgumentParser(
        prog="familylink fetch-config",
        description=(
            "Read the current Family Link supervision state for every child and write "
            "a config CSV that reproduces it. Blocked apps are excluded (absence = blocked). "
            "Always-allowed and time-limited apps are included."
        ),
    )
    parser.add_argument(
        "--browser",
        choices=["firefox", "chrome"],
        default="firefox",
        help="Browser to read cookies from (default: firefox)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=".",
        help="Directory for output CSV files (default: current directory)",
    )
    args = parser.parse_args(argv)

    from familylink.models import AlwaysAllowedState

    client = FamilyLink(browser=args.browser)
    members = client.get_members()
    children = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]

    if not children:
        console.print("[error]No supervised accounts found.[/error]")
        sys.exit(1)

    out_dir = Path(args.output_dir)
    multi = len(children) > 1

    def _day_nums_to_range_strs(nums: list[int]) -> list[str]:
        """[1,2,3,4,5] → ['Mon-Fri']  |  [1,2,3,4,5,7] → ['Mon-Fri','Sun']  |  all 7 → ['']"""
        _D = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
        s = sorted(nums)
        if s == list(range(1, 8)):
            return [""]
        runs, run = [], [s[0]]
        for n in s[1:]:
            if n == run[-1] + 1:
                run.append(n)
            else:
                runs.append(run)
                run = [n]
        runs.append(run)
        return [_D[r[0]] if len(r) == 1 else f"{_D[r[0]]}-{_D[r[-1]]}" for r in runs]

    for child in children:
        given = child.profile.given_name or child.profile.display_name.split()[0]
        safe = "".join(c for c in given if c.isalnum() or c in "-_")
        filename = f"config-{safe}.csv" if multi else "config.csv"
        out_path = out_dir / filename

        console.print(
            f"Fetching settings for [bold]{child.profile.display_name}[/bold]..."
        )
        usage = client.get_apps_and_usage(child.user_id)

        # Fetch and parse the device schedule (downtime + screen-time limits)
        schedule: dict[int, dict] = {}
        try:
            r = client._session.get(
                f"{client.BASE_URL}/people/{child.user_id}/timeLimit"
            )
            if r.is_success:
                schedule = parsers.parse_time_limit(r.json())
        except Exception:
            pass

        # Group day numbers (1=Mon…7=Sun) by their available time window
        from collections import defaultdict

        time_groups: dict[str, list[int]] = defaultdict(list)
        for d in range(1, 8):
            info = schedule.get(d, {})
            key = (
                f"{info['avail_start']}-{info['avail_end']}"
                if "avail_start" in info
                else ""
            )
            time_groups[key].append(d)
        # Sort groups so earlier days come first
        sorted_groups = sorted(time_groups.items(), key=lambda kv: kv[1][0])

        rows = []
        for app in sorted(usage.apps, key=lambda a: a.title.lower()):
            sup = app.supervision_setting
            is_system = any(
                app.package_name.startswith(p) for p in ["com.google", "com.android"]
            )

            if sup.hidden:
                continue  # excluded — absence keeps it blocked

            if sup.usage_limit:
                # One row per day-group × consecutive day-range within that group
                dur = _mins_to_hhmm(sup.usage_limit.daily_usage_limit_mins)
                for time_range, day_nums in sorted_groups:
                    for days_str in _day_nums_to_range_strs(day_nums):
                        rows.append(
                            {
                                "App": app.title,
                                "Max Duration": dur,
                                "Days": days_str,
                                "Time Ranges": time_range,
                            }
                        )
            elif (
                sup.always_allowed_app_info
                and sup.always_allowed_app_info.always_allowed_state
                == AlwaysAllowedState.ENABLED
            ) or not is_system:
                # Always-allowed (or permitted unmanaged) — no time restriction
                rows.append(
                    {
                        "App": app.title,
                        "Max Duration": "",
                        "Days": "",
                        "Time Ranges": "",
                    }
                )

        n_limited = sum(1 for r in rows if r["Max Duration"])
        n_always = len(rows) - n_limited

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["App", "Max Duration", "Days", "Time Ranges"]
            )
            writer.writeheader()
            writer.writerows(rows)

        console.print(
            f"[success]Saved {out_path}[/success] — "
            f"{n_limited} time-limited rows, {n_always} always allowed"
        )

    if multi:
        console.print(
            "\n[dim]One file per supervised member. Pass the right file as the config argument "
            "and set account_id to target the matching member.[/dim]"
        )


def main():
    """Main entry point for the CLI"""
    if len(sys.argv) > 1 and sys.argv[1] == "export-cookies":
        _cmd_export_cookies(sys.argv[2:])
        return

    if len(sys.argv) > 1 and sys.argv[1] == "fetch-config":
        _cmd_fetch_config(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(
        description="Apply Family Link configuration from CSV file"
    )
    parser.add_argument(
        "config_file",
        nargs="?",
        default="config.csv",
        help="Path to the configuration CSV file (default: config.csv)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not apply changes, just print what would be done",
    )
    parser.add_argument(
        "--cookie-file",
        help="Path to the cookie file to use",
    )
    parser.add_argument(
        "--browser",
        choices=["firefox", "chrome"],
        default="firefox",
        help="Browser to use",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("httpx").setLevel(logging.DEBUG)

    if args.dry_run:
        console.rule("[yellow]DRY RUN MODE[/yellow]")
        console.print("[yellow]No changes will be applied[/yellow]")
        console.rule()

    client_kwargs = {}

    if args.cookie_file:
        client_kwargs["cookie_file_path"] = Path(args.cookie_file)

    if args.browser:
        client_kwargs["browser"] = args.browser

    try:
        client = FamilyLink(**client_kwargs)

        if not Path(args.config_file).exists():
            _create_default_config(client, args.config_file)
            return

        config = _load_config(args.config_file)
        _apply_config(client, config, args.dry_run)
    except SessionExpiredError as e:
        console.print(f"[error]Session expired:[/error] {e}")
        sys.exit(1)


def _parse_duration(duration_str: str) -> int:
    """Convert duration string (H:MM) to minutes"""
    if not duration_str:
        return 0
    parts = duration_str.split(":")
    if len(parts) == 2:
        hours, minutes = map(int, parts)
        return hours * 60 + minutes
    return 0


def _parse_days(days_str: str) -> list[str]:
    """Convert day range (e.g., 'Mon-Wed' or 'Fri') to list of days"""
    if not days_str:
        return []

    days_map = {
        "mon": "monday",
        "tue": "tuesday",
        "wed": "wednesday",
        "thu": "thursday",
        "fri": "friday",
        "sat": "saturday",
        "sun": "sunday",
    }

    all_days = list(days_map.values())
    if "-" in days_str:
        start, end = days_str.lower().split("-")
        start_idx = list(days_map.keys()).index(start)
        end_idx = list(days_map.keys()).index(end)
        selected_days = all_days[start_idx : end_idx + 1]
        return selected_days
    else:
        return [days_map[days_str.lower()]]


def _load_config(config_file="config.csv"):
    apps_config = {}

    with open(config_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            app = row["App"].strip()
            days = row["Days"].strip()
            time_ranges = row["Time Ranges"].strip()
            duration = row["Max Duration"].strip()

            # Handle always allowed apps (empty fields)
            if not any([days, time_ranges, duration]):
                apps_config[app] = {"always_allowed": True}
                continue

            if app not in apps_config:
                apps_config[app] = {"schedules": {}, "limits": {}}

            if not days:
                days = "mon-sun"

            if not time_ranges:
                time_ranges = "00:00-23:59"

            for day in _parse_days(days):
                if time_ranges:
                    apps_config[app]["schedules"][day] = time_ranges
                if duration:
                    apps_config[app]["limits"][day] = _parse_duration(duration)

    return apps_config


def _get_expected_limits(config: dict) -> dict[str, bool | int]:
    expected_limits = dict[str, bool | int]()
    now = datetime.now()
    today = now.strftime("%A").lower()

    for app, settings in config.items():
        if settings.get("always_allowed"):
            expected_limits[app] = True
        elif limit := settings["limits"].get(today):
            if schedules := settings["schedules"].get(today):
                for schedule in schedules.split(";"):
                    start, end = schedule.split("-")
                    if start <= now.time().strftime("%H:%M") <= end:
                        expected_limits[app] = limit
                        break
            else:
                expected_limits[app] = limit
    return expected_limits


def _apply_config(client: FamilyLink, config: dict, dry_run: bool = True):
    expected_limits = _get_expected_limits(config)
    child_id = client._ensure_account_id()
    app_usage = client.get_apps_and_usage(child_id)
    pkg_by_title = {app.title: app.package_name for app in app_usage.apps}

    # {"Always allowed app": True, "Limited app": 120, "Blocked app": False,
    # "Unsupervised app": None}
    current_limit_per_app = dict[str, bool | int]()

    for app in app_usage.apps:
        if limit := app.supervision_setting.usage_limit:
            current_limit_per_app[app.title] = limit.daily_usage_limit_mins
        elif app.supervision_setting.hidden:
            current_limit_per_app[app.title] = False
        elif (
            app.supervision_setting.always_allowed_app_info
            and app.supervision_setting.always_allowed_app_info.always_allowed_state
            == AlwaysAllowedState.ENABLED
        ):
            current_limit_per_app[app.title] = True
        elif not any(
            app.package_name.startswith(prefix)
            for prefix in ["com.google", "com.android"]
        ):
            # Apps that are not supervised yet (recent installs for example)
            current_limit_per_app[app.title] = None

    for app, limit in current_limit_per_app.items():
        if expected_limit := expected_limits.get(app):
            if expected_limit == limit:
                console.print(
                    f"[dim]• '{app}' is already set to the expected limit[/dim]"
                )
            elif expected_limit is True:
                console.print(f"[success]• Setting '{app}' to unlimited[/success]")
                if not dry_run:
                    if pkg := pkg_by_title.get(app):
                        client.always_allow_app(pkg, child_id)
            else:
                console.print(
                    f"[info]• Setting '{app}' to {expected_limit} min[/info]"
                    f"[dim] (previously {limit})[/dim]"
                )
                if not dry_run:
                    if pkg := pkg_by_title.get(app):
                        client.set_app_limit(pkg, expected_limit, child_id)

        elif limit is not False:
            console.print(
                f"[warning]• Blocking '{app}'[/warning][dim] (previously {limit})[/dim]"
            )
            if not dry_run:
                if pkg := pkg_by_title.get(app):
                    client.block_app(pkg, child_id)


def _create_default_config(client: FamilyLink, config_file: str):
    """Create a default config file with all apps and 0:00 limit"""
    child_id = client._ensure_account_id()
    app_usage = client.get_apps_and_usage(child_id)

    with open(config_file, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "App",
                "Max Duration",
                "Days",
                "Time Ranges",
            ],
        )
        writer.writeheader()
        for app in sorted(app_usage.apps, key=lambda x: x.title):
            writer.writerow(
                {
                    "App": app.title,
                    "Max Duration": "0:00",
                    "Days": "",
                    "Time Ranges": "",
                }
            )
    console.print(f"[success]Created default config file at {config_file}[/success]")


if __name__ == "__main__":
    main()
