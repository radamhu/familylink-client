# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stacked-section dashboard with a compact status-strip layout: one strip per child showing screen time at a glance, expanding inline to show top apps, devices, and Linux machine detail.

**Architecture:** Each child occupies a wrapper `<div id="child-{user_id}">` whose innerHTML is swapped by HTMX. The collapsed state renders `partials/child_strip.html`; clicking loads `/children/{child_id}/detail` which returns `partials/child_expanded.html` (strip in expanded style + detail panel). Clicking the expanded strip header calls `/children/{child_id}/collapse` to restore the collapsed partial. The Apps page kid switcher receives the same color-coded avatars for visual consistency.

**Tech Stack:** FastAPI + Jinja2 templates, Pico CSS v2, HTMX 1.9, SQLAlchemy async, Python 3.12

## Global Constraints

- No new Python or JS dependencies — stay on Pico CSS v2 + HTMX 1.9
- Ruff linting must pass: `ruff check src tests`
- All tests must pass: `python -m pytest`
- Inline styles only (no new CSS files) — existing pattern in codebase
- Expanded view is read-only — no action buttons in the expanded panel
- Colors assigned by child index, cycling through `CHILD_COLORS` list

---

## File Map

| Action | File |
|--------|------|
| Modify | `src/familylink_server/routers/dashboard.py` |
| Modify | `src/familylink_server/routers/apps.py` |
| Rewrite | `src/familylink_server/templates/dashboard.html` |
| Create | `src/familylink_server/templates/partials/child_strip.html` |
| Create | `src/familylink_server/templates/partials/child_expanded.html` |
| Modify | `src/familylink_server/templates/apps.html` |
| Modify | `tests/server/test_routers_dashboard.py` |

---

### Task 1: Refactor `dashboard.py` — extract `_get_child_data` helper

Extract the per-child data-building logic into a reusable helper function and add `color`, `is_locked`, and `device_count` fields to the child dict. The existing `GET /` route is simplified to call the helper. No visual change yet — existing tests must still pass.

**Files:**
- Modify: `src/familylink_server/routers/dashboard.py`

**Interfaces:**
- Produces:
  - `CHILD_COLORS: list[str]` — module-level constant, indexed by child position
  - `_get_child_data(child: Any, idx: int, svc: FamilyLinkService, session: AsyncSession) -> dict` — returns child dict with keys: `display_name`, `user_id`, `color`, `total_seconds`, `top5`, `devices`, `linux_machines`, `is_locked`, `device_count`
  - Child dict `color` field: `str` hex color (e.g. `"#a855f7"`)
  - Child dict `is_locked` field: `bool` — True if any device is locked
  - Child dict `device_count` field: `int`

- [ ] **Step 1: Add `from typing import Any` import and `CHILD_COLORS` constant**

Replace the imports block and add the constant in `src/familylink_server/routers/dashboard.py`:

```python
"""Router for the main dashboard page."""

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from familylink_server.auth.oauth import require_user
from familylink_server.db import get_session
from familylink_server.db.models import LinuxMachine, LinuxUsageSnapshot
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

CHILD_COLORS = ["#a855f7", "#3b82f6", "#10b981", "#f59e0b", "#ef4444"]
```

- [ ] **Step 2: Add `_get_child_data` helper function** (place before `dashboard` route)

```python
async def _get_child_data(
    child: Any,
    idx: int,
    svc: FamilyLinkService,
    session: AsyncSession,
) -> dict:
    """Build the template data dict for a single supervised child."""
    today = date.today()
    usage = await svc.get_apps_and_usage(child.user_id)
    today_sessions = [
        s
        for s in usage.app_usage_sessions
        if s.date.year == today.year
        and s.date.month == today.month
        and s.date.day == today.day
    ]
    total_seconds = sum(int(float(s.usage)) for s in today_sessions)
    top_apps: dict[str, int] = {}
    for s in today_sessions:
        pkg = s.app_id.android_app_package_name
        top_apps[pkg] = top_apps.get(pkg, 0) + int(float(s.usage))
    top5 = sorted(top_apps.items(), key=lambda x: x[1], reverse=True)[:5]
    title_by_pkg = {a.package_name: a.title for a in usage.apps}
    top5_named = [
        {"title": title_by_pkg.get(pkg, pkg), "seconds": secs} for pkg, secs in top5
    ]
    devices = [
        {
            "device_id": d.device_id,
            "friendly_name": d.display_info.friendly_name,
            "is_locked": False,
        }
        for d in usage.device_info
    ]
    machine_result = await session.execute(
        select(LinuxMachine).where(
            LinuxMachine.child_id == child.user_id,
            LinuxMachine.enabled.is_(True),
        )
    )
    machines = machine_result.scalars().all()
    linux_rows = []
    for m in machines:
        snap_result = await session.execute(
            select(LinuxUsageSnapshot).where(
                LinuxUsageSnapshot.machine_id == m.id,
                LinuxUsageSnapshot.date == today,
            )
        )
        snap = snap_result.scalar_one_or_none()
        active_mins = (snap.active_seconds // 60) if snap else 0
        bonus_mins = snap.bonus_mins if snap else 0
        effective_limit_mins = (
            m.daily_limit_mins + bonus_mins
            if m.daily_limit_mins is not None
            else None
        )
        if snap and snap.poweroff_at:
            lm_status = "powered_off"
        elif snap and snap.locked_at:
            lm_status = "locked"
        else:
            lm_status = "active"
        linux_rows.append(
            {
                "friendly_name": m.friendly_name,
                "active_mins": active_mins,
                "effective_limit_mins": effective_limit_mins,
                "status": lm_status,
            }
        )
    is_locked = any(d["is_locked"] for d in devices)
    return {
        "display_name": child.profile.display_name,
        "user_id": child.user_id,
        "color": CHILD_COLORS[idx % len(CHILD_COLORS)],
        "total_seconds": total_seconds,
        "top5": top5_named,
        "devices": devices,
        "linux_machines": linux_rows,
        "is_locked": is_locked,
        "device_count": len(devices),
    }
```

- [ ] **Step 3: Simplify the `dashboard` route to use `_get_child_data`**

Replace the existing `dashboard` function body:

```python
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Render the dashboard with per-child usage summaries."""
    members = await svc.get_members()
    supervised = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    child_data = [
        await _get_child_data(child, idx, svc, session)
        for idx, child in enumerate(supervised)
    ]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"children": child_data, "auth_failed": svc.auth_failed},
    )
```

- [ ] **Step 4: Run existing dashboard tests — must pass**

```bash
python -m pytest tests/server/test_routers_dashboard.py -v
```

Expected: all three tests PASS (`test_dashboard_returns_200`, `test_dashboard_shows_linux_machine_for_child`, `test_history_returns_200`)

- [ ] **Step 5: Run linter**

```bash
ruff check src/familylink_server/routers/dashboard.py
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/familylink_server/routers/dashboard.py
git commit -m "refactor: extract _get_child_data helper, add color/is_locked/device_count fields"
```

---

### Task 2: Create `child_strip.html` partial + rewrite `dashboard.html`

Replace the verbose `<section>` layout with compact status strips. Each child gets a wrapper div targeted by HTMX. The strip partial is self-contained and reused by the collapse route in Task 4.

**Files:**
- Create: `src/familylink_server/templates/partials/child_strip.html`
- Rewrite: `src/familylink_server/templates/dashboard.html`

**Interfaces:**
- Consumes: child dict from Task 1 (`display_name`, `user_id`, `color`, `total_seconds`, `is_locked`, `device_count`)
- Produces: `partials/child_strip.html` template — requires `child` variable in Jinja2 context

- [ ] **Step 1: Create `partials/child_strip.html`**

```html
<div style="display:flex;align-items:center;padding:11px 14px;gap:12px;cursor:pointer"
     hx-get="/children/{{ child.user_id }}/detail"
     hx-target="#child-{{ child.user_id }}"
     hx-swap="innerHTML">
  <div style="width:36px;height:36px;border-radius:50%;background:{{ child.color }};color:white;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px;flex-shrink:0">{{ child.display_name[0] | upper }}</div>
  <div style="flex:1">
    <div style="font-weight:600;font-size:13px;color:#1f2937">{{ child.display_name }}</div>
    <div style="font-size:10px;color:#6b7280;margin-top:1px">📱 {{ child.device_count }} device{{ 's' if child.device_count != 1 else '' }}</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:19px;font-weight:700;color:{{ '#dc2626' if child.is_locked else '#1f2937' }};line-height:1.1">
      {{ child.total_seconds // 3600 }}h {{ (child.total_seconds % 3600) // 60 }}m
    </div>
    <div style="font-size:10px;color:{{ '#ef4444' if child.is_locked else '#22c55e' }};margin-top:2px">
      ● {{ 'locked' if child.is_locked else 'unlocked' }}
    </div>
  </div>
  <div style="color:#d1d5db;font-size:12px;margin-left:4px">▶</div>
</div>
```

- [ ] **Step 2: Rewrite `dashboard.html`**

```html
{% extends "base.html" %}
{% block title %}Dashboard{% endblock %}
{% block content %}
<div hx-get="/" hx-trigger="every 5m" hx-target="main" hx-swap="innerHTML">
  {% if children %}
    <div style="background:white;border-radius:10px;overflow:hidden;border:1px solid #e5e7eb;margin-bottom:0.5rem">
      {% for child in children %}
        {% if not loop.first %}
          <div style="height:1px;background:#f3f4f6;margin:0 14px"></div>
        {% endif %}
        <div id="child-{{ child.user_id }}">
          {% include "partials/child_strip.html" %}
        </div>
      {% endfor %}
    </div>
    <p style="font-size:0.75rem;color:var(--pico-muted-color);text-align:center;margin:0">auto-refreshes every 5 min</p>
  {% else %}
    <p>No supervised children found.</p>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 3: Add a test that verifies strip structure**

In `tests/server/test_routers_dashboard.py`, add after the existing tests:

```python
def test_dashboard_strips_show_child_name_and_color():
    """Dashboard renders a strip per child with colored avatar and name."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child = MagicMock()
    child.user_id = 'child1'
    child.profile.display_name = 'Alice'
    child.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Alice' in resp.text
    assert 'id="child-child1"' in resp.text
    assert '#a855f7' in resp.text  # first child gets purple
    assert 'hx-get="/children/child1/detail"' in resp.text
```

- [ ] **Step 4: Run tests — must pass**

```bash
python -m pytest tests/server/test_routers_dashboard.py -v
```

Expected: all four tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/templates/dashboard.html \
        src/familylink_server/templates/partials/child_strip.html \
        tests/server/test_routers_dashboard.py
git commit -m "feat: replace dashboard sections with compact status strips"
```

---

### Task 3: Add `/children/{child_id}/detail` route + `child_expanded.html` partial

When a strip is tapped, HTMX calls this route and replaces the child wrapper's innerHTML with an expanded view: strip in highlighted state (chevron down, colored left border) plus a read-only detail panel showing top apps, devices, and Linux machines.

**Files:**
- Create: `src/familylink_server/templates/partials/child_expanded.html`
- Modify: `src/familylink_server/routers/dashboard.py` (add route)
- Modify: `tests/server/test_routers_dashboard.py` (add test)

**Interfaces:**
- Consumes: `_get_child_data` from Task 1, `CHILD_COLORS` from Task 1
- Produces: `GET /children/{child_id}/detail` → HTML partial (replaces `#child-{child_id}` innerHTML)

- [ ] **Step 1: Create `partials/child_expanded.html`**

```html
<div style="display:flex;align-items:center;padding:11px 14px;gap:12px;cursor:pointer;background:#f8fafc;border-left:3px solid {{ child.color }}"
     hx-get="/children/{{ child.user_id }}/collapse"
     hx-target="#child-{{ child.user_id }}"
     hx-swap="innerHTML">
  <div style="width:36px;height:36px;border-radius:50%;background:{{ child.color }};color:white;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px;flex-shrink:0">{{ child.display_name[0] | upper }}</div>
  <div style="flex:1">
    <div style="font-weight:600;font-size:13px;color:#1f2937">{{ child.display_name }}</div>
    <div style="font-size:10px;color:#6b7280;margin-top:1px">📱 {{ child.device_count }} device{{ 's' if child.device_count != 1 else '' }}</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:19px;font-weight:700;color:{{ '#dc2626' if child.is_locked else '#1f2937' }};line-height:1.1">
      {{ child.total_seconds // 3600 }}h {{ (child.total_seconds % 3600) // 60 }}m
    </div>
    <div style="font-size:10px;color:{{ '#ef4444' if child.is_locked else '#22c55e' }};margin-top:2px">
      ● {{ 'locked' if child.is_locked else 'unlocked' }}
    </div>
  </div>
  <div style="color:{{ child.color }};font-size:12px;margin-left:4px">▼</div>
</div>
<div style="padding:0 14px 12px 17px;border-left:3px solid {{ child.color }};background:#f8fafc">
  {% if child.top5 %}
    <div style="font-size:10px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;padding-top:8px">Top apps today</div>
    {% set max_secs = [child.top5[0].seconds, 1] | max %}
    {% for app in child.top5 %}
      <div style="display:flex;align-items:center;gap:6px;font-size:11px;margin-bottom:3px">
        <span style="width:80px;color:#374151;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ app.title }}</span>
        <div style="flex:1;background:#e5e7eb;border-radius:2px;height:7px">
          <div style="background:{{ child.color }};height:7px;border-radius:2px;width:{{ (app.seconds / max_secs * 100) | int }}%"></div>
        </div>
        <span style="color:#6b7280;width:28px;text-align:right;flex-shrink:0">{{ app.seconds // 60 }}m</span>
      </div>
    {% endfor %}
  {% endif %}
  {% if child.devices %}
    <div style="font-size:10px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:5px;margin-top:10px">Devices</div>
    <div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:2px">
      {% for device in child.devices %}
        <div style="border-radius:6px;padding:3px 8px;font-size:10px;{% if device.is_locked %}background:#fee2e2;color:#991b1b{% else %}background:#dcfce7;color:#166534{% endif %}">
          📱 {{ device.friendly_name or device.device_id }} {% if device.is_locked %}🔒{% else %}🔓{% endif %}
        </div>
      {% endfor %}
    </div>
  {% endif %}
  {% if child.linux_machines %}
    <div style="font-size:10px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:5px;margin-top:10px">Linux machines</div>
    {% for lm in child.linux_machines %}
      <div style="display:flex;align-items:center;gap:6px;font-size:11px;margin-bottom:4px">
        <span style="width:80px;color:#374151;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ lm.friendly_name }}</span>
        {% if lm.effective_limit_mins %}
          <div style="flex:1;background:#e5e7eb;border-radius:2px;height:7px">
            <div style="height:7px;border-radius:2px;width:{{ [[((lm.active_mins / lm.effective_limit_mins) * 100) | int, 0] | max, 100] | min }}%;background:{% if lm.active_mins >= lm.effective_limit_mins %}#ef4444{% elif lm.active_mins >= lm.effective_limit_mins * 0.8 %}#f59e0b{% else %}{{ child.color }}{% endif %}"></div>
          </div>
          <span style="color:#6b7280;width:50px;text-align:right;flex-shrink:0;font-size:10px">{{ lm.active_mins }}/{{ lm.effective_limit_mins }}m</span>
        {% else %}
          <span style="color:#6b7280;font-size:10px;flex:1">no limit</span>
        {% endif %}
        {% if lm.status == 'powered_off' %}
          <span title="powered off">🔴</span>
        {% elif lm.status == 'locked' %}
          <span title="locked">🟠</span>
        {% else %}
          <span title="active">🟢</span>
        {% endif %}
      </div>
    {% endfor %}
  {% endif %}
</div>
```

- [ ] **Step 2: Add the detail route to `dashboard.py`** (place after the `dashboard` route)

```python
@router.get('/children/{child_id}/detail', response_class=HTMLResponse)
async def child_detail(
    child_id: str,
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Return expanded child detail partial for HTMX swap."""
    members = await svc.get_members()
    supervised = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    idx = next((i for i, m in enumerate(supervised) if m.user_id == child_id), 0)
    child = next((m for m in supervised if m.user_id == child_id), None)
    if child is None:
        return HTMLResponse('', status_code=404)
    child_data = await _get_child_data(child, idx, svc, session)
    return templates.TemplateResponse(
        request,
        'partials/child_expanded.html',
        {'child': child_data},
    )
```

- [ ] **Step 3: Write the failing test**

In `tests/server/test_routers_dashboard.py`, add:

```python
def test_child_detail_returns_expanded_view():
    """GET /children/{child_id}/detail returns the expanded partial with child name and top apps."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child = MagicMock()
    child.user_id = 'child1'
    child.profile.display_name = 'Alice'
    child.member_supervision_info.is_supervised_member = True

    session_mock = MagicMock()
    session_mock.app_id.android_app_package_name = 'com.example'
    today = __import__('datetime').date.today()
    session_mock.date = today
    session_mock.usage = '1800'

    app_mock = MagicMock()
    app_mock.package_name = 'com.example'
    app_mock.title = 'Example App'

    usage = MagicMock()
    usage.app_usage_sessions = [session_mock]
    usage.apps = [app_mock]
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/children/child1/detail', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Alice' in resp.text
    assert 'Example App' in resp.text
    assert 'hx-get="/children/child1/collapse"' in resp.text


def test_child_detail_returns_404_for_unknown_child():
    """GET /children/{child_id}/detail returns 404 when child_id not found."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[]))
    mock_svc.auth_failed = False

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/children/nobody/detail', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 404
```

- [ ] **Step 4: Run tests — all must pass**

```bash
python -m pytest tests/server/test_routers_dashboard.py -v
```

Expected: all six tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/templates/partials/child_expanded.html \
        src/familylink_server/routers/dashboard.py \
        tests/server/test_routers_dashboard.py
git commit -m "feat: add child detail expand route and partial"
```

---

### Task 4: Add `/children/{child_id}/collapse` route

When the expanded strip header is tapped, HTMX calls this route. It returns `child_strip.html` content, restoring the child wrapper to its collapsed state.

**Files:**
- Modify: `src/familylink_server/routers/dashboard.py` (add route)
- Modify: `tests/server/test_routers_dashboard.py` (add test)

**Interfaces:**
- Consumes: `_get_child_data` from Task 1, `child_strip.html` from Task 2
- Produces: `GET /children/{child_id}/collapse` → HTML partial (collapses `#child-{child_id}` back to strip)

- [ ] **Step 1: Add the collapse route to `dashboard.py`** (place after `child_detail` route)

```python
@router.get('/children/{child_id}/collapse', response_class=HTMLResponse)
async def child_collapse(
    child_id: str,
    request: Request,
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Return collapsed child strip partial for HTMX swap."""
    members = await svc.get_members()
    supervised = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    idx = next((i for i, m in enumerate(supervised) if m.user_id == child_id), 0)
    child = next((m for m in supervised if m.user_id == child_id), None)
    if child is None:
        return HTMLResponse('', status_code=404)
    child_data = await _get_child_data(child, idx, svc, session)
    return templates.TemplateResponse(
        request,
        'partials/child_strip.html',
        {'child': child_data},
    )
```

- [ ] **Step 2: Write the failing test**

In `tests/server/test_routers_dashboard.py`, add:

```python
def test_child_collapse_returns_strip():
    """GET /children/{child_id}/collapse returns the collapsed strip partial."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child = MagicMock()
    child.user_id = 'child1'
    child.profile.display_name = 'Alice'
    child.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    app.dependency_overrides[get_service] = lambda: mock_svc
    app.dependency_overrides[get_session] = _fake_session()
    try:
        client = TestClient(app)
        resp = client.get('/children/child1/collapse', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    assert 'Alice' in resp.text
    assert 'hx-get="/children/child1/detail"' in resp.text
    assert '▶' in resp.text
```

- [ ] **Step 3: Run all dashboard tests**

```bash
python -m pytest tests/server/test_routers_dashboard.py -v
```

Expected: all seven tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/familylink_server/routers/dashboard.py \
        tests/server/test_routers_dashboard.py
git commit -m "feat: add child collapse route"
```

---

### Task 5: Update Apps page — add color to children + avatar initials in kid switcher

Add the `color` field to each child dict in `apps.py` and update `apps.html` to show the matching colored avatar initial in the kid switcher tabs.

**Files:**
- Modify: `src/familylink_server/routers/apps.py`
- Modify: `src/familylink_server/templates/apps.html`
- Modify: `tests/server/test_routers_apps.py` (add one assertion)

**Interfaces:**
- Consumes: `CHILD_COLORS` pattern from Task 1 (duplicated here — no shared import needed)
- Produces: `children` list items in apps template context now include `color: str`

- [ ] **Step 1: Add `CHILD_COLORS` constant and update `children` list in `apps.py`**

Near the top of `src/familylink_server/routers/apps.py`, after the existing imports, add:

```python
CHILD_COLORS = ['#a855f7', '#3b82f6', '#10b981', '#f59e0b', '#ef4444']
```

In the `apps_page` function, replace the `children` list comprehension:

```python
    children = [
        {
            'user_id': m.user_id,
            'display_name': m.profile.display_name,
            'color': CHILD_COLORS[i % len(CHILD_COLORS)],
        }
        for i, m in enumerate(supervised)
    ]
```

- [ ] **Step 2: Update the kid switcher nav in `apps.html`**

Replace the existing kid switcher `<nav>` block (lines 11–19 of `apps.html`):

```html
  {% if children | length > 1 %}
  <nav>
    {% for c in children %}
      <a href="/apps?child={{ c.user_id }}&filter={{ filter }}"
         {% if c.user_id == active_child_id %}aria-current="page"{% endif %}
         style="display:inline-flex;align-items:center;gap:5px;text-decoration:none">
        <span style="width:18px;height:18px;border-radius:50%;background:{{ c.color }};color:white;font-size:9px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0">{{ c.display_name[0] | upper }}</span>
        {{ c.display_name }}
      </a>
    {% endfor %}
  </nav>
  {% endif %}
```

- [ ] **Step 3: Run existing apps tests — must pass**

```bash
python -m pytest tests/server/test_routers_apps.py -v
```

Expected: all existing tests PASS

- [ ] **Step 4: Verify avatar appears in rendered page**

Add a quick check in `tests/server/test_routers_apps.py`. Find the existing test that renders the apps page with multiple children (or add one):

```python
def test_apps_page_kid_switcher_shows_avatar():
    """Apps page kid switcher renders colored avatar initial when multiple children exist."""
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    child1 = MagicMock()
    child1.user_id = 'c1'
    child1.profile.display_name = 'Alice'
    child1.member_supervision_info.is_supervised_member = True

    child2 = MagicMock()
    child2.user_id = 'c2'
    child2.profile.display_name = 'Bob'
    child2.member_supervision_info.is_supervised_member = True

    usage = MagicMock()
    usage.app_usage_sessions = []
    usage.apps = []
    usage.device_info = []

    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(return_value=MagicMock(members=[child1, child2]))
    mock_svc.get_apps_and_usage = AsyncMock(return_value=usage)
    mock_svc.auth_failed = False

    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    assert '#a855f7' in resp.text   # first child color
    assert '#3b82f6' in resp.text   # second child color
```

Note: `_cookie()` and `AsyncMock` are already imported in `test_routers_apps.py`. Check the file first — if `_cookie` has a different import pattern there, match it.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/server/ -v
```

Expected: all tests PASS

- [ ] **Step 6: Run linter**

```bash
ruff check src tests
```

Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/familylink_server/routers/apps.py \
        src/familylink_server/templates/apps.html \
        tests/server/test_routers_apps.py
git commit -m "feat: add colored avatar initials to apps page kid switcher"
```
