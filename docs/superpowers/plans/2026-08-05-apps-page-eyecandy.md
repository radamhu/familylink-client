# Apps Page Eyecandy Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the Apps page (`apps.html` + `partials/app_row.html`) from a bare Pico `<details>`/`<table>` layout to the card/pill visual language already used on the Dashboard, with zero backend or data-shape changes.

**Architecture:** Two Jinja2 templates are edited in place. `partials/app_row.html`'s outer element changes from `<tr>` to a flex `<div>` (status becomes a colored pill badge, action buttons become styled chips) so it can be embedded directly in a card body instead of a `<table>`. `apps.html`'s child sections change from bare `<details>`+`<table>` to a rounded card per child (colored avatar header, like `child_strip.html`) wrapping a list of `app_row.html` includes, and the filter `<nav>` becomes a segmented pill control. All `hx-post`/`hx-target`/`hx-swap` attributes, template variable names, and the `app` dict shape are unchanged, so `routers/apps.py` needs no edits.

**Tech Stack:** Jinja2 templates, Pico CSS v2 (CDN), HTMX (CDN), inline styles only (codebase has no `<style>` blocks or custom CSS file — do not introduce one).

## Global Constraints

- No changes to `routers/apps.py` or any other Python file — this is a template-only restyle.
- No new HTTP endpoints, no new template context variables.
- Every existing `hx-post` URL, `hx-target` (`#row-{{ package-with-dots-as-dashes }}`), and `hx-swap="outerHTML"` in `app_row.html` must be preserved byte-for-byte.
- Status → color mapping stays: blocked=red, limited=orange/amber, allowed=green, unmanaged=grey.
- Preserve exact text the test suite asserts on (see Task 1 & 2 test files): `'YouTube'`, `'Emma'`, `'Lucas'`, `'Emma</a>' not in resp.text`, `'href="/apps?filter=all'`, `'#a855f7'`, `'#3b82f6'`, `'Auto-block on overuse'`, `'checked'`, `'+15 min'`, `'+30 min'`, `'+60 min'`.
- No `<style>` tag, no new CDN dependency — match the existing inline-style-only convention used in `dashboard.html`/`child_strip.html`/`child_expanded.html`.

---

### Task 1: Restyle the app row partial

**Files:**
- Modify: `src/familylink_server/templates/partials/app_row.html`
- Test: `tests/server/test_routers_apps.py` (existing, no new test file needed — this is a markup-only change with no new behavior to unit test)

**Interfaces:**
- Consumes: `app` dict with keys `package_name`, `title`, `state` (`"blocked"|"limited"|"allowed"|"unmanaged"`), `state_label`, `limit_mins`, `child_id`, `auto_block_enabled`, `auto_blocked_at` — unchanged, defined in `routers/apps.py::_app_state` and the four POST handlers.
- Produces: a `<div id="row-{{ package-with-dots-as-dashes }}">` root element (was `<tr id="row-...">`) that `hx-swap="outerHTML"` targets — later inclusion in `apps.html` (Task 2) relies on this being a block-level element valid as a direct child of a `<div>`, not a `<table>`.

- [ ] **Step 1: Run the existing test suite as a baseline**

Run: `python -m pytest tests/server/test_routers_apps.py -v`
Expected: all tests PASS (confirms starting point before the markup change).

- [ ] **Step 2: Replace `app_row.html` with the restyled markup**

Replace the full contents of `src/familylink_server/templates/partials/app_row.html` with:

```html
<div id="row-{{ app.package_name | replace('.', '-') }}"
     style="display:flex;align-items:center;gap:10px;padding:10px 14px;border-top:1px solid #f3f4f6">
  <div style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.85rem;color:#1f2937">{{ app.title }}</div>

  {% if app.state == "blocked" %}
    <span style="background:#fee2e2;color:#991b1b;border-radius:10px;padding:2px 10px;font-size:0.7rem;font-weight:600;white-space:nowrap">Blocked</span>
  {% elif app.state == "limited" %}
    <span style="background:#fef3c7;color:#92400e;border-radius:10px;padding:2px 10px;font-size:0.7rem;font-weight:600;white-space:nowrap">{{ app.state_label }}</span>
  {% elif app.state == "allowed" %}
    <span style="background:#dcfce7;color:#166534;border-radius:10px;padding:2px 10px;font-size:0.7rem;font-weight:600;white-space:nowrap">Always allowed</span>
  {% else %}
    <span style="background:#f3f4f6;color:#4b5563;border-radius:10px;padding:2px 10px;font-size:0.7rem;font-weight:600;white-space:nowrap">Unmanaged</span>
  {% endif %}

  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0">
    <details>
      <summary role="button" class="outline secondary" style="font-size:0.7rem;padding:3px 12px;border-radius:20px">Edit</summary>
      <div style="padding:0.5rem 0 0.25rem;display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end">
        <form hx-post="/apps/{{ app.package_name }}/allow"
              hx-target="#row-{{ app.package_name | replace('.', '-') }}"
              hx-swap="outerHTML" style="display:inline">
          <input type="hidden" name="child_id" value="{{ app.child_id }}">
          <button type="submit" style="font-size:0.7rem;padding:3px 10px;border-radius:20px;border:1px solid #86efac;background:#f0fdf4;color:#166534;cursor:pointer">Always allow</button>
        </form>
        <form hx-post="/apps/{{ app.package_name }}/block"
              hx-target="#row-{{ app.package_name | replace('.', '-') }}"
              hx-swap="outerHTML" style="display:inline">
          <input type="hidden" name="child_id" value="{{ app.child_id }}">
          <button type="submit" style="font-size:0.7rem;padding:3px 10px;border-radius:20px;border:1px solid #fca5a5;background:#fef2f2;color:#991b1b;cursor:pointer">Block</button>
        </form>
        <form hx-post="/apps/{{ app.package_name }}/limit"
              hx-target="#row-{{ app.package_name | replace('.', '-') }}"
              hx-swap="outerHTML"
              style="display:inline-flex;align-items:center;gap:4px;border:1px solid #e5e7eb;border-radius:20px;padding:2px 4px 2px 10px;background:#f8fafc">
          <input type="hidden" name="child_id" value="{{ app.child_id }}">
          <input type="number" name="minutes" value="{{ app.limit_mins or 30 }}"
                 min="1" max="1440" style="width:3.5rem;border:none;background:transparent;padding:0;font-size:0.7rem">
          <button type="submit" style="font-size:0.7rem;padding:3px 10px;border-radius:16px;border:none;background:#e5e7eb;color:#374151;cursor:pointer">Set limit</button>
        </form>
      </div>
    </details>
    {% if app.state == "limited" %}
      <form hx-post="/apps/{{ app.package_name }}/auto-block"
            hx-trigger="change"
            hx-target="#row-{{ app.package_name | replace('.', '-') }}"
            hx-swap="outerHTML" style="display:inline">
        <input type="hidden" name="child_id" value="{{ app.child_id }}">
        <input type="hidden" name="limit_mins" value="{{ app.limit_mins }}">
        <label style="font-size:0.7rem;display:inline-flex;align-items:center;gap:4px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:20px;padding:3px 10px 3px 6px;white-space:nowrap;cursor:pointer">
          <input type="checkbox" name="enabled" value="true" {{ 'checked' if app.auto_block_enabled }} style="margin:0">
          Auto-block on overuse
        </label>
      </form>
    {% endif %}
    {% if app.auto_blocked_at %}
      <form hx-post="/apps/{{ app.package_name }}/bonus"
            hx-target="#row-{{ app.package_name | replace('.', '-') }}"
            hx-swap="outerHTML" style="display:flex;gap:4px">
        <input type="hidden" name="child_id" value="{{ app.child_id }}">
        {% for mins in [15, 30, 60] %}
          <button type="submit" name="minutes" value="{{ mins }}" style="font-size:0.7rem;padding:3px 9px;border-radius:14px;border:1px solid #93c5fd;background:#eff6ff;color:#1d4ed8;cursor:pointer">+{{ mins }} min</button>
        {% endfor %}
      </form>
    {% endif %}
  </div>
</div>
```

- [ ] **Step 3: Run the test suite again to confirm no regressions**

Run: `python -m pytest tests/server/test_routers_apps.py -v`
Expected: all tests PASS — in particular `test_auto_block_toggle_renders_checked` (or equivalent) still finds `'checked'` and `'Auto-block on overuse'`, and the bonus-minutes test still finds `'+15 min'`, `'+30 min'`, `'+60 min'`.

- [ ] **Step 4: Commit**

```bash
git add src/familylink_server/templates/partials/app_row.html
git commit -m "style: restyle app row as pill-badge flex row

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Restyle the apps page shell (filter nav + per-child cards)

**Files:**
- Modify: `src/familylink_server/templates/apps.html`
- Test: `tests/server/test_routers_apps.py` (existing)

**Interfaces:**
- Consumes: `children` (list of `{user_id, display_name, color, apps}` dicts, `color` a hex string from `CHILD_COLORS`), `filter` (one of `"all"|"allowed"|"limited"|"blocked"`), `auth_failed` — all from `routers/apps.py::apps_page`, unchanged.
- Consumes: `partials/app_row.html` (Task 1) via `{% include %}` — depends on that partial's root being a `<div>`, not a `<tr>`.
- Produces: nothing consumed elsewhere — this is the page template.

- [ ] **Step 1: Run the existing test suite as a baseline**

Run: `python -m pytest tests/server/test_routers_apps.py -v`
Expected: all tests PASS (Task 1's row change already in place and green).

- [ ] **Step 2: Replace `apps.html` with the restyled markup**

Replace the full contents of `src/familylink_server/templates/apps.html` with:

```html
{% extends "base.html" %}
{% block title %}Apps{% endblock %}
{% block content %}
<div hx-get="/apps?filter={{ filter }}"
     hx-trigger="every 5m"
     hx-target="main"
     hx-swap="innerHTML">

  <h2>Apps</h2>

  <nav style="display:inline-flex;gap:2px;background:#f1f5f9;padding:3px;border-radius:10px;margin-bottom:1rem">
    {% for f in ["all", "allowed", "limited", "blocked"] %}
      {% set pill_color = {"all": "#6b7280", "allowed": "#22c55e", "limited": "#f59e0b", "blocked": "#ef4444"}[f] %}
      <a href="/apps?filter={{ f }}"
         {% if filter == f %}aria-current="page"{% endif %}
         style="padding:5px 14px;border-radius:8px;font-size:0.8rem;font-weight:600;text-decoration:none;white-space:nowrap;
                {% if filter == f %}background:{{ pill_color }};color:white{% else %}color:#6b7280{% endif %}">{{ f | capitalize }}</a>
    {% endfor %}
  </nav>

  {% if children %}
    {% for child in children %}
      <details {% if loop.first %}open{% endif %}
                style="margin-bottom:0.75rem;border-radius:10px;border:1px solid #e5e7eb;overflow:hidden;background:white">
        <summary style="display:flex;align-items:center;gap:10px;cursor:pointer;padding:12px 14px;background:#f8fafc">
          <span style="width:28px;height:28px;border-radius:50%;background:{{ child.color }};color:white;font-size:12px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0">{{ child.display_name[0] | upper }}</span>
          <span style="font-weight:600;font-size:14px;color:#1f2937">{{ child.display_name }}</span>
          <span style="font-size:0.7rem;color:var(--pico-muted-color);background:#e5e7eb;border-radius:10px;padding:1px 9px">{{ child.apps | length }}</span>
        </summary>
        <div>
          {% for app in child.apps %}
            {% include "partials/app_row.html" %}
          {% else %}
            <div style="padding:14px;color:var(--pico-muted-color);font-size:0.85rem">No apps found.</div>
          {% endfor %}
        </div>
      </details>
    {% endfor %}
  {% else %}
    <p>No supervised children found.</p>
  {% endif %}

</div>
{% endblock %}
```

- [ ] **Step 3: Run the test suite again to confirm no regressions**

Run: `python -m pytest tests/server/test_routers_apps.py -v`
Expected: all tests PASS — in particular the substring checks for `'Emma'`, `'Lucas'`, `'Emma</a>' not in resp.text`, `'href="/apps?filter=all'`, `'#a855f7'`, `'#3b82f6'`.

- [ ] **Step 4: Commit**

```bash
git add src/familylink_server/templates/apps.html
git commit -m "style: redesign apps page as pill filter nav + per-kid cards

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Full-suite verification

**Files:** none (verification only)

**Interfaces:** none — this task only runs commands.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest`
Expected: all tests PASS, no failures introduced anywhere else in the codebase (e.g. `test_routers_dashboard.py`, which shares `CHILD_COLORS`/avatar conventions, should be unaffected since it renders a different template).

- [ ] **Step 2: Lint the two changed templates' surrounding Python is untouched, and check git status is clean**

Run: `git status --short`
Expected: clean working tree (everything already committed in Task 1 and Task 2).

- [ ] **Step 3: Update graphify's index for the changed templates**

Run: `graphify update .`
Expected: completes without error, refreshing the AST-derived graph for the two modified template files.
