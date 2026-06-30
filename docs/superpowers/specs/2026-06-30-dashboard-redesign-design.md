# Dashboard Redesign — Design Spec

**Date:** 2026-06-30
**Status:** Approved

## Context

The current dashboard stacks each child in a plain `<section>` with no visual boundary between kids, making it hard to scan on mobile. The redesign makes screen time the hero metric and separates kids clearly with a compact strip-based layout.

## Constraints

- 3+ kids supported
- Mobile-first, works on desktop too
- Primary glance metric: screen time total per kid
- Stay on Pico CSS v2 + HTMX — no new dependencies
- No framework changes to other pages except minor consistency update to Apps

## Dashboard — Status Strips

### Strip list

All kids appear in a single card as stacked strips divided by thin lines. Each strip contains:

- **Left:** Colored avatar circle with the kid's initial (color assigned by index: purple, blue, green, orange, red for kids 1–5)
- **Center:** Kid's name (bold), device count below in muted text
- **Right:** Screen time (large, bold) — turns red when kid is locked or usage is high; lock status dot (green `● unlocked` / red `● locked`); chevron arrow (▶ collapsed / ▼ expanded)

### Expand / collapse

Tapping a strip expands an inline detail panel directly below it, with a colored left border matching the kid's avatar color. Only one kid can be expanded at a time — opening a second one collapses the first.

The expanded panel is read-only and shows three sections in order:

1. **Top apps today** — app name, mini horizontal bar chart (bars in the kid's color), time in minutes
2. **Devices** — one pill/chip per device showing name and locked/unlocked icon; locked chips have red background
3. **Linux machines** (if any) — machine name, progress bar (yellow when near limit), `used / limit min` label, status emoji (🟢 active / 🟠 locked / 🔴 powered off)

The expand/collapse is implemented with HTMX: the strip row has `hx-get="/<child_id>/detail"` and `hx-swap="afterend"`. A second tap removes the detail row (toggle pattern). The detail is an HTML partial rendered server-side.

### Auto-refresh

Unchanged from current behavior: `hx-trigger="every 5m"` on the outer wrapper refreshes the whole dashboard content.

## Apps Page — Kid Switcher

Minor consistency update only: the existing `<nav>` tab links for kid selection get the same colored avatar initials as the dashboard strips (same color-by-index rule), so each kid has a consistent visual identity across the whole app. The table, filters, and app row partial are unchanged.

## Color Assignment

Colors are assigned by the kid's position in the list returned by the API (0-indexed):

| Index | Color   | Hex       |
|-------|---------|-----------|
| 0     | Purple  | `#a855f7` |
| 1     | Blue    | `#3b82f6` |
| 2     | Green   | `#10b981` |
| 3     | Orange  | `#f59e0b` |
| 4     | Red     | `#ef4444` |

No configuration needed — derived at render time in the Jinja2 template using a `loop.index0` lookup into a color list.

## Out of Scope

- Action buttons in the expanded view (lock/unlock, set limits) — these remain on the dedicated Devices and Apps pages
- Devices page, History page, Linux Machines page — no changes
- Dark mode, theming, branding changes
