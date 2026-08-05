# Apps Page Eyecandy Redesign — Design Spec

**Date:** 2026-08-05
**Status:** Approved

## Context

The Apps page (`apps.html` + `partials/app_row.html`) still uses a bare Pico `<details>`/`<table>` layout with plain colored status text and cramped inline-styled buttons. Meanwhile the Dashboard (`child_strip.html`, `child_expanded.html`, `device_card.html`) already established a polished card language — rounded card container, colored avatar strip per kid, pill/chip badges, hairline dividers. This redesign brings the Apps page up to that same visual language.

## Constraints

- Pure front-end restyle: no router (`routers/apps.py`) or data-shape changes. `app_row.html` keeps receiving the exact same `app` dict.
- Stay on Pico CSS v2 + HTMX — no new dependencies, no build step.
- Keep the existing status → color mapping (blocked=red, limited=orange, allowed=green, unmanaged=grey) and the `CHILD_COLORS` per-kid avatar color assignment already used elsewhere.
- All existing `hx-post` targets/swaps in `app_row.html` (`/apps/{package}/limit`, `/allow`, `/block`, `/auto-block`, `/bonus`) are unchanged so every endpoint in `apps.py` keeps working untouched.
- No usage-today data (out of scope — see below).

## Apps Page — Filter Nav

The current `<nav>` of plain text links becomes a segmented pill control: one rounded pill container holding 4 pills (All / Allowed / Limited / Blocked). The active pill is filled with its status color (grey for "All", green/orange/red for the others); inactive pills are transparent with muted text. Same 4 `<a href="/apps?filter=...">` links, no JS.

## Apps Page — Per-Kid Cards

Each supervised kid becomes a rounded card (`border-radius:10px; border:1px solid #e5e7eb; overflow:hidden`), replacing the bare `<details>` block:

- **Header** (the `<summary>`, still a native disclosure toggle): colored avatar circle with initial (reuses the same `CHILD_COLORS[i]` value already passed to the template), kid's display name (bold), app count as a small muted badge, chevron indicator. Visually modeled on `child_strip.html`.
- **Body**: app rows stacked with `1px` hairline dividers between them (`background:#f3f4f6`), replacing the `<table>`/`<tr>` structure. Same one-child-open-by-default behavior (`{% if loop.first %}open{% endif %}`) is kept.

## App Row — Status & Actions

Each row (`partials/app_row.html`) keeps its `id="row-{{ package }}"` (htmx swap target) but restyles:

- **Status** becomes a pill badge: colored background + colored text, rounded, ~11px font — same color-per-state mapping as today, styled like the `device_card.html` chips instead of bare colored `<span>` text.
- **Edit** stays a `<details>`/`<summary role="button">` disclosure (approved: keeps rows scannable when a kid has many apps) but the summary button and the panel inside get restyled:
  - Allow / Block buttons become small filled-outline pill buttons tinted with their target state's color (green for allow, red for block) instead of default Pico `outline`/`outline secondary`.
  - The limit form's number input + submit become a single compact chip-style control (rounded, bordered, ~0.75rem).
  - The auto-block checkbox label becomes a small toggle-styled chip instead of a plain checkbox+text line.
  - The bonus-minutes buttons (`+15/+30/+60 min`) become small colored chips in a row, matching the app-usage chip look used on the dashboard.

## Out of Scope

- No usage-today numbers or progress bars on app rows (no `apps.py` change to fetch per-app usage seconds for this page).
- No change to `dashboard.html`, `devices.html`, `history.html`, `linux_machines.html`, or their partials.
- No dark mode / theming changes — light theme only, same as today.
- No new htmx endpoints or behavior changes — every POST target and swap stays identical to current `apps.py`.
