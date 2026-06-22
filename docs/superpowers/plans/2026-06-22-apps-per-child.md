# Apps Per-Child View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded single-child `/apps` page with a tab-strip per-child view that shows live app data with a 5-minute HTMX auto-refresh.

**Architecture:** The `GET /apps` router gains a `child` query param; it eager-loads all supervised children (cached), resolves the active child, and fetches that child's apps. The template renders a child tab strip (when >1 child) above the existing filter nav, and wraps everything in an HTMX auto-refresh div.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, HTMX 1.9, PicoCSS 2, pytest with `asyncio_mode = "auto"`, `unittest.mock`.

## Global Constraints

- Do not use `uv` — use `pip` and `python -m pytest` directly.
- `PYTHONPATH=src` must be set (handled by direnv or `pytest` config).
- `asyncio_mode = "auto"` — all `async def test_*` are awaited automatically.
- Server tests set required env vars in `tests/server/conftest.py` via `os.environ.setdefault` — do not add new env vars.
- Ruff is the linter/formatter; single-quoted strings; Google docstring style.
- No changes to `partials/app_row.html`, mutation endpoints, or `FamilyLinkService`.

---

## File Map

| File | Change |
|---|---|
| `src/familylink_server/routers/apps.py` | Add `child` query param; resolve active child; pass `children` + `active_child_id` to template |
| `src/familylink_server/templates/apps.html` | Add HTMX refresh wrapper, child tab strip, updated filter links |
| `tests/server/test_routers_apps.py` | Update existing tests + add 4 new tests |

---

## Task 1: Update the router

**Files:**
- Modify: `src/familylink_server/routers/apps.py`
- Test: `tests/server/test_routers_apps.py`

**Interfaces:**
- Produces: `GET /apps?child=<id>&filter=<f>` — template context keys `children` (list of `{"user_id": str, "display_name": str}`), `active_child_id` (str), `apps` (list of app dicts with `child_id`), `filter` (str).

- [ ] **Step 1: Write the new failing tests**

Open `tests/server/test_routers_apps.py` and add these four tests at the bottom of the file (do not delete existing tests):

```python
def _make_member(user_id, display_name, supervised=True):
    m = MagicMock()
    m.user_id = user_id
    m.profile.display_name = display_name
    m.member_supervision_info = MagicMock(is_supervised_member=supervised)
    return m


def _make_usage(*app_mocks):
    u = MagicMock()
    u.apps = list(app_mocks)
    u.device_info = []
    u.app_usage_sessions = []
    return u


def test_apps_page_shows_child_tabs_for_multiple_children():
    """Tab links for both children appear when two supervised children exist."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(
            members=[
                _make_member('child1', 'Emma'),
                _make_member('child2', 'Lucas'),
            ]
        )
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(_make_app_mock('YouTube', 'com.google.android.youtube'))
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    assert 'Emma' in resp.text
    assert 'Lucas' in resp.text
    assert 'href="/apps?child=child1' in resp.text
    assert 'href="/apps?child=child2' in resp.text


def test_apps_page_child_param_selects_correct_child():
    """?child=child2 fetches child2's apps, not child1's."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(
            members=[
                _make_member('child1', 'Emma'),
                _make_member('child2', 'Lucas'),
            ]
        )
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(_make_app_mock('Minecraft', 'com.mojang.minecraftpe'))
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.get('/apps?child=child2', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    mock_svc.get_apps_and_usage.assert_called_once_with('child2')


def test_apps_page_invalid_child_falls_back_to_first():
    """Unknown child param silently falls back to children[0]."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(
            members=[_make_member('child1', 'Emma')]
        )
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(_make_app_mock('YouTube', 'com.google.android.youtube'))
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.get('/apps?child=unknown-id', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    mock_svc.get_apps_and_usage.assert_called_once_with('child1')


def test_apps_page_single_child_no_tab_links():
    """With one child the response contains no child= tab links."""
    mock_svc = MagicMock()
    mock_svc.get_members = AsyncMock(
        return_value=MagicMock(
            members=[_make_member('child1', 'Emma')]
        )
    )
    mock_svc.get_apps_and_usage = AsyncMock(
        return_value=_make_usage(_make_app_mock('YouTube', 'com.google.android.youtube'))
    )
    from familylink_server.main import app
    from familylink_server.services.family_link import get_service

    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        client = TestClient(app)
        resp = client.get('/apps', cookies={'fl_session': _cookie()})
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert resp.status_code == 200
    assert 'href="/apps?child=child1' not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/server/test_routers_apps.py::test_apps_page_shows_child_tabs_for_multiple_children tests/server/test_routers_apps.py::test_apps_page_child_param_selects_correct_child tests/server/test_routers_apps.py::test_apps_page_invalid_child_falls_back_to_first tests/server/test_routers_apps.py::test_apps_page_single_child_no_tab_links -v
```

Expected: 4 FAILs (the tab assertions will fail because the router still hardcodes `children[0]`).

- [ ] **Step 3: Implement the updated router**

Replace the entire content of `src/familylink_server/routers/apps.py` with:

```python
"""Router for the /apps HTML page and HTMX limit/block/allow endpoints."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(tags=['apps'])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / 'templates'))


def _app_state(app) -> dict:
    sup = app.supervision_setting
    if sup.hidden:
        state, state_label = 'blocked', 'Blocked'
    elif sup.usage_limit:
        state, state_label = (
            'limited',
            f'Limited {sup.usage_limit.daily_usage_limit_mins} min',
        )
    elif sup.always_allowed_app_info:
        state, state_label = 'allowed', 'Always allowed'
    else:
        state, state_label = 'unmanaged', 'Unmanaged'
    return {
        'package_name': app.package_name,
        'title': app.title,
        'state': state,
        'state_label': state_label,
        'limit_mins': sup.usage_limit.daily_usage_limit_mins if sup.usage_limit else None,
    }


@router.get('/apps', response_class=HTMLResponse)
async def apps_page(
    request: Request,
    filter: str = 'all',
    child: str = '',
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Render the apps page with a per-child tab strip and inline edit controls."""
    members = await svc.get_members()
    supervised = [
        m
        for m in members.members
        if m.member_supervision_info and m.member_supervision_info.is_supervised_member
    ]
    children = [
        {'user_id': m.user_id, 'display_name': m.profile.display_name}
        for m in supervised
    ]

    child_ids = {c['user_id'] for c in children}
    active_child_id = child if child in child_ids else (children[0]['user_id'] if children else '')

    apps = []
    if active_child_id:
        usage = await svc.get_apps_and_usage(active_child_id)
        apps = [
            dict(_app_state(a), child_id=active_child_id)
            for a in sorted(usage.apps, key=lambda x: x.title.lower())
        ]
        if filter != 'all':
            apps = [a for a in apps if a['state'] == filter]

    return templates.TemplateResponse(
        request,
        'apps.html',
        {
            'apps': apps,
            'children': children,
            'active_child_id': active_child_id,
            'filter': filter,
        },
    )


@router.post('/apps/{package}/limit', response_class=HTMLResponse)
async def set_limit(
    package: str,
    request: Request,
    child_id: str = Form(...),
    minutes: int = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Set a daily usage limit for an app and return the updated row partial."""
    await svc.set_app_limit(package, minutes, child_id=child_id)
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'limited',
        'state_label': f'Limited {minutes} min',
        'limit_mins': minutes,
        'child_id': child_id,
    }
    return templates.TemplateResponse(request, 'partials/app_row.html', {'app': app_data})


@router.post('/apps/{package}/block', response_class=HTMLResponse)
async def block_app(
    package: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Block an app and return the updated row partial."""
    await svc.block_app(package, child_id=child_id)
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'blocked',
        'state_label': 'Blocked',
        'limit_mins': None,
        'child_id': child_id,
    }
    return templates.TemplateResponse(request, 'partials/app_row.html', {'app': app_data})


@router.post('/apps/{package}/allow', response_class=HTMLResponse)
async def allow_app(
    package: str,
    request: Request,
    child_id: str = Form(...),
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> HTMLResponse:
    """Always-allow an app and return the updated row partial."""
    await svc.always_allow_app(package, child_id=child_id)
    app_data = {
        'package_name': package,
        'title': package,
        'state': 'allowed',
        'state_label': 'Always allowed',
        'limit_mins': None,
        'child_id': child_id,
    }
    return templates.TemplateResponse(request, 'partials/app_row.html', {'app': app_data})
```

- [ ] **Step 4: Run all new tests to verify they pass**

```bash
python -m pytest tests/server/test_routers_apps.py -v
```

Expected: all tests PASS (including the 3 pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add src/familylink_server/routers/apps.py tests/server/test_routers_apps.py
git commit -m "feat: add per-child tab support to /apps router"
```

---

## Task 2: Update the template

**Files:**
- Modify: `src/familylink_server/templates/apps.html`

**Interfaces:**
- Consumes: template context from Task 1 — `children` (list of `{"user_id": str, "display_name": str}`), `active_child_id` (str), `apps` (list), `filter` (str).

- [ ] **Step 1: Replace apps.html**

Replace the entire content of `src/familylink_server/templates/apps.html` with:

```html
{% extends "base.html" %}
{% block title %}Apps{% endblock %}
{% block content %}
<div hx-get="/apps?child={{ active_child_id }}&filter={{ filter }}"
     hx-trigger="every 5m"
     hx-target="main"
     hx-swap="innerHTML">

  <h2>Apps</h2>

  {% if children | length > 1 %}
  <nav>
    {% for c in children %}
      <a href="/apps?child={{ c.user_id }}&filter={{ filter }}"
         {% if c.user_id == active_child_id %}aria-current="page"{% endif %}>
        {{ c.display_name }}
      </a>
    {% endfor %}
  </nav>
  {% endif %}

  <nav>
    {% for f in ["all", "allowed", "limited", "blocked"] %}
      <a href="/apps?child={{ active_child_id }}&filter={{ f }}"
         {% if filter == f %}aria-current="page"{% endif %}>{{ f | capitalize }}</a>
    {% endfor %}
  </nav>

  <table>
    <thead><tr><th>App</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>
      {% for app in apps %}
        {% include "partials/app_row.html" %}
      {% else %}
        <tr><td colspan="3">No apps found.</td></tr>
      {% endfor %}
    </tbody>
  </table>

</div>
{% endblock %}
```

- [ ] **Step 2: Verify the full test suite still passes**

```bash
python -m pytest tests/server/test_routers_apps.py -v
```

Expected: all tests PASS. The template change has no new logic — the new tests in Task 1 already cover the HTML assertions (`child=child1` links present/absent, display names in output).

- [ ] **Step 3: Manual smoke test**

Start the dev server:
```bash
uvicorn familylink_server.main:app --reload
```

Open `http://localhost:8000/apps` and verify:
- If you have one child: no child tabs visible, filter nav works, apps load.
- If you have two+ children: child tabs appear above filter nav; clicking a tab switches to that child's apps; the filter is preserved in the URL.
- Wait or trigger the HTMX refresh by observing network requests every 5 minutes (or temporarily change `every 5m` to `every 5s` in the template, verify the refresh fires, then revert).

- [ ] **Step 4: Commit**

```bash
git add src/familylink_server/templates/apps.html
git commit -m "feat: per-child tab strip and live refresh on /apps page"
```
