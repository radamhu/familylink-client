# Apps Page — Per-Child View Design

**Date:** 2026-06-22
**Status:** Approved

## Problem

The `/apps` page hardcodes `children[0]`, so only the first supervised child's apps are ever shown. There is no live refresh. The dashboard already demonstrates the correct pattern: eager-load all children, render per-child sections, auto-refresh every 5 minutes.

## Goal

Show apps scoped to one child at a time with a tab strip for switching children, live data refresh every 5 minutes, and the existing filter nav (all/allowed/limited/blocked) preserved.

---

## Architecture

### Router (`src/familylink_server/routers/apps.py`)

`GET /apps` gains a `child` query param (default: first supervised child's `user_id`).

Request flow:
1. `svc.get_members()` — fetch all supervised children (TTL-cached).
2. Resolve active child: use `child` param if it matches a known supervised `user_id`, else fall back to `children[0]`.
3. `svc.get_apps_and_usage(active_child.user_id)` — fetch apps for the active child only.
4. Pass to template: `children` (list of `{user_id, display_name}`), `active_child_id`, `apps`, `filter`.

Mutation endpoints (`POST /apps/{package}/limit|block|allow`) are **unchanged** — they already carry `child_id` as a hidden form field.

### URL structure

```
/apps                              → first child, filter=all
/apps?child=<id>                   → specific child, filter=all
/apps?child=<id>&filter=limited    → specific child, specific filter
```

Tab links preserve the current filter. Filter links preserve the current child.

---

## Template (`src/familylink_server/templates/apps.html`)

Layout (top to bottom):

```
[Child 1 tab]  [Child 2 tab]       ← child tab strip (omitted if single child)
[All] [Allowed] [Limited] [Blocked] ← filter nav (unchanged)
──────────────────────────────────
App table (partials/app_row.html)  ← unchanged
```

Live refresh wrapper:
```html
<div hx-get="/apps?child={{ active_child_id }}&filter={{ filter }}"
     hx-trigger="every 5m"
     hx-target="main"
     hx-swap="innerHTML">
```

Child tab strip (rendered only when `children|length > 1`):
```html
<nav>
  {% for child in children %}
    <a href="/apps?child={{ child.user_id }}&filter={{ filter }}"
       {% if child.user_id == active_child_id %}aria-current="page"{% endif %}>
      {{ child.display_name }}
    </a>
  {% endfor %}
</nav>
```

Filter nav links change to `/apps?child={{ active_child_id }}&filter={{ f }}`.

`partials/app_row.html` — **no changes needed**.

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| Invalid/stale `child` param | Silently fall back to `children[0]` |
| No supervised children | Show "No supervised children found." (existing guard) |
| Single child | Tab strip hidden; page looks unchanged but gains 5-min live refresh |
| Filter + child yields no apps | Existing "No apps found." empty-state row |
| HTMX refresh with open edit panel | `<details>` is replaced on refresh; acceptable at 5-minute interval |

---

## What Does Not Change

- `partials/app_row.html` — no modifications
- Mutation endpoints (`/limit`, `/block`, `/allow`) — no modifications
- `FamilyLinkService` — no modifications
- PicoCSS styling conventions — tab strip uses the same `<nav>` + `aria-current` pattern as the existing filter nav
