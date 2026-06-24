"""Discord embed builder functions."""

from __future__ import annotations

import datetime

import discord

_ACTION_MAP: dict[str, tuple[str, discord.Color]] = {
    "block": ("🔒 App Blocked", discord.Color.red()),
    "always_allow": ("✅ App Always Allowed", discord.Color.green()),
    "set_limit": ("⏱️ App Limit Set", discord.Color.orange()),
    "lock_device": ("🔒 Device Locked", discord.Color.orange()),
    "unlock_device": ("🔓 Device Unlocked", discord.Color.green()),
}


def _fmt(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _bar(value: int, max_value: int, width: int = 10) -> str:
    if max_value == 0:
        return "░" * width
    filled = round(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


def change_embed(
    action: str, child_name: str, target: str, source: str
) -> discord.Embed:
    """Return an embed describing a single Family Link write action."""
    title, color = _ACTION_MAP.get(
        action,
        (f'ℹ️ {action.replace("_", " ").title()}', discord.Color.blurple()),
    )
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Child", value=child_name, inline=True)
    embed.add_field(name="Target", value=target, inline=True)
    embed.add_field(name="By", value=source, inline=True)
    return embed


def apps_list_embed(
    apps: list[dict],
    child_name: str,
    page: int,
    total_pages: int,
) -> discord.Embed:
    """Return a paginated embed listing apps and their current state."""
    embed = discord.Embed(
        title=f"📱 Apps — {child_name}  (page {page}/{total_pages})",
        color=discord.Color.blurple(),
    )
    for app in apps:
        embed.add_field(
            name=app["title"],
            value=app["state_label"],
            inline=True,
        )
    return embed


def devices_list_embed(devices: list[dict], child_name: str) -> discord.Embed:
    """Return an embed listing devices and their lock state."""
    embed = discord.Embed(
        title=f"📱 Devices — {child_name}", color=discord.Color.blurple()
    )
    for d in devices:
        lock_icon = "🔒" if d.get("is_locked") else "🔓"
        embed.add_field(
            name=d.get("friendly_name") or d["device_id"],
            value=lock_icon,
            inline=True,
        )
    return embed


def usage_today_embed(
    child_name: str, top_apps: list[dict], total_seconds: int
) -> discord.Embed:
    """Return a bar-chart embed of today's top app usage."""
    today = datetime.date.today().strftime("%A %d %b").lstrip(" ").replace(" ", " ", 1)
    # Format: "Monday 24 Jun" (no leading zero on day)
    parts = today.split()
    day_str = str(int(parts[1])) if len(parts) > 1 else parts[0]
    today = f"{parts[0]} {day_str} {parts[2]}" if len(parts) > 2 else today
    embed = discord.Embed(
        title=f"📊 Today — {child_name}  ·  {today}",
        description=f"Total: **{_fmt(total_seconds)}**",
        color=discord.Color.blurple(),
    )
    max_s = max((a["seconds"] for a in top_apps), default=1)
    for app in top_apps[:10]:
        embed.add_field(
            name=app["title"],
            value=f'`{_bar(app["seconds"], max_s)}` {_fmt(app["seconds"])}',
            inline=False,
        )
    return embed


def usage_history_embed(
    child_name: str, daily_totals: list[dict], days: int
) -> discord.Embed:
    """Return an embed with per-day usage totals."""
    embed = discord.Embed(
        title=f"📈 History — {child_name}  (last {days} days)",
        color=discord.Color.blurple(),
    )
    max_s = max((d["seconds"] for d in daily_totals), default=1)
    for day in daily_totals:
        embed.add_field(
            name=day["date"],
            value=f'`{_bar(day["seconds"], max_s)}` {_fmt(day["seconds"])}',
            inline=False,
        )
    return embed


def status_embed(children_data: list[dict]) -> discord.Embed:
    """Return a dashboard overview embed covering all children."""
    embed = discord.Embed(title="🏠 Family Status", color=discord.Color.blurple())
    for child in children_data:
        devices = f'{child["device_count"]} device(s)'
        embed.add_field(
            name=child["name"],
            value=f'{_fmt(child["total_seconds"])} today · {devices}',
            inline=False,
        )
    return embed


def daily_summary_embed(
    child_name: str, top_apps: list[dict], total_seconds: int
) -> discord.Embed:
    """Return a daily summary embed (used by the scheduled task)."""
    today = datetime.date.today().strftime("%A %d %b").lstrip(" ").replace(" ", " ", 1)
    # Format: "Monday 24 Jun" (no leading zero on day)
    parts = today.split()
    day_str = str(int(parts[1])) if len(parts) > 1 else parts[0]
    today = f"{parts[0]} {day_str} {parts[2]}" if len(parts) > 2 else today
    embed = discord.Embed(
        title=f"📊 Daily Summary — {child_name}  ·  {today}",
        description=f"Total screen time: **{_fmt(total_seconds)}**",
        color=discord.Color.blurple(),
    )
    max_s = max((a["seconds"] for a in top_apps), default=1)
    for app in top_apps[:5]:
        embed.add_field(
            name=app["title"],
            value=f'`{_bar(app["seconds"], max_s)}` {_fmt(app["seconds"])}',
            inline=False,
        )
    return embed
