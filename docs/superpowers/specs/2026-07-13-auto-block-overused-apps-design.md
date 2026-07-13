# Auto-Block Overused Apps — Design Spec

**Date:** 2026-07-13
**Status:** Pending approval

## Overview

Google Family Link's own daily usage limit for an app (e.g. Viber, YouTube Kids) sometimes doesn't actually block the app once the limit is hit — the kid keeps using it. This adds a background enforcer that watches a parent-selected set of apps per child and, if live usage reaches the app's configured Google-side daily limit, actively calls `block_app()` itself rather than trusting Google's enforcement. The app auto-unblocks (limit restored) at the next local-day rollover. Not all apps are covered — only ones a parent explicitly opts in per child. A parent can also grant bonus time to unblock early; if the bonus is also exceeded, the enforcer re-blocks the same way.

## Data Model

`AppConfig` (`app_configs`, currently unused — only exported, never read/written) gets two new columns and becomes the opt-in + bookkeeping record. It does **not** duplicate the daily limit minutes — the threshold is always read live from Google (`app.supervision_setting.usage_limit.daily_usage_limit_mins`) at poll time, so there's no second copy of the limit that can drift out of sync.

| Column | Type | Notes |
|---|---|---|
| `auto_block_enabled` | bool NOT NULL DEFAULT false | Parent opt-in — this app is in the "predefined list" to enforce for this child |
| `auto_blocked_at` | datetime NULL | Set when the enforcer blocks the app for overuse; cleared on next-day restore or on bonus grant. `None` means either never auto-blocked, or a manual block by the parent (not ours to auto-restore) |
| `bonus_mins` | int NOT NULL DEFAULT 0 | Extra minutes a parent granted today, added to the live Google limit when computing the effective cap |
| `bonus_date` | date NULL | The local date `bonus_mins` applies to. If it isn't today, the effective bonus is treated as 0 — no explicit daily reset write needed |

Existing `max_mins`, `days_mask`, `time_range`, `always_allowed`, `blocked` columns are left as-is (unused by this feature; out of scope to wire up).

Lookup key is `(child_id, package_name)`. Alembic migration adds the two columns plus a unique constraint on `(child_id, package_name)`, since the table has none today and the enforcer needs get-or-create semantics.

Alembic migration: `004_auto_block_overused_apps.py`.

## Enforcement Logic (`services/app_enforcer.py`, new file)

Mirrors the shape of `services/linux_poller.py`.

```python
POLL_INTERVAL = 300  # 5 min
```

`enforce_child(child_id, svc, session)`:
1. `usage = await svc.get_apps_and_usage(child_id, bypass_cache=True)` — force-refreshed live call (see service change below), so enforcement isn't bounded by the dashboard's 900s TTL.
2. Sum today's `AppUsageSession.usage` per `package_name` (usage sessions are separate from `usage.apps`, joined by package name — same pattern `apps.py` and `usage.py` already use).
3. Load all `AppConfig` rows for `child_id` where `auto_block_enabled` is true, keyed by `package_name`.
4. For each such row, find the matching `App` in `usage.apps` to read its live `supervision_setting.usage_limit.daily_usage_limit_mins`. If there's no active Google-side limit (app is unmanaged/always-allowed/already hidden), skip — nothing to enforce against.
5. Compute `effective_limit = daily_usage_limit_mins + (bonus_mins if bonus_date == today else 0)`.
6. **Trigger block:** if `usage_mins >= effective_limit` and `auto_blocked_at is None` → `await svc.block_app(package_name, child_id)`, set `auto_blocked_at = now(UTC)`, write `AuditLog(action='auto_block', child_id=child_id, target=package_name, new_value=f'{usage_mins}/{effective_limit} min')`. This is the same check whether the app is over its base limit or has already burned through granted bonus — a bonus grant just raises the number being checked against.
7. **Daily restore:** if `auto_blocked_at is not None` and `auto_blocked_at.date() < today` (local date) → `await svc.set_app_limit(package_name, restore_minutes, child_id)` to lift the block and reapply a limit for the new day, clear `auto_blocked_at = None`, write `AuditLog(action='auto_unblock', ...)`. `restore_minutes` is the same `daily_usage_limit_mins` value read from Google in step 4 for that child+app on this cycle (Google retains the configured limit value even while hidden/blocked, since `block_app` and `set_app_limit` write different fields on the same restriction object). Note `bonus_mins`/`bonus_date` are left untouched here — they naturally stop applying once `bonus_date` is no longer today.

`enforce_child` is wrapped in try/except inside the loop; one child's failure doesn't stop others (`asyncio.gather(..., return_exceptions=True)`, same as `poller_loop`).

`app_enforcer_loop(notifier=None)`: same `while True: ... asyncio.sleep(POLL_INTERVAL)` shape as `poller_loop`, iterating all children who have at least one `auto_block_enabled` row. On auto-block, if `notifier` is set, call `notifier.notify_change('auto_block', child_name, package_name, 'enforcer')` (mirrors the Linux poller's lock notification).

### `remove_app_limit` is not used for restore

`FamilyLink.remove_app_limit()` (`client.py:377`) sends the identical payload as `block_app()` — its name is misleading, it does not clear a block. Restoring access must call `set_app_limit(package_name, minutes, child_id)` again.

## Service Change (`services/family_link.py`)

`get_apps_and_usage` gains a `bypass_cache: bool = False` parameter:

```python
async def get_apps_and_usage(self, child_id: str, bypass_cache: bool = False) -> AppUsage:
    if not bypass_cache:
        cached = self._usage_cache.get(child_id)
        if cached and self._is_fresh(cached[1]):
            return cached[0]
    result = await asyncio.to_thread(self._client.get_apps_and_usage, child_id)
    self._usage_cache[child_id] = (result, datetime.now(UTC))
    return result
```

Existing callers (dashboard, apps page, bot) are unaffected — default stays cached.

## Wiring (`main.py`)

Same pattern as the Linux poller:

```python
enforcer_task = asyncio.create_task(app_enforcer_loop(notifier=notifier))
logger.info('App overuse enforcer started')
...
enforcer_task.cancel()
with contextlib.suppress(asyncio.CancelledError):
    await enforcer_task
```

## Web UI (`routers/apps.py`, `templates/partials/app_row.html`)

`apps_page()` gains a `session: AsyncSession = Depends(get_session)` parameter, queries `AppConfig` rows for `active_child_id` where `auto_block_enabled`, and passes `auto_block_enabled: bool` into each app dict from `_app_state()`.

New checkbox in `app_row.html`, shown only when the app's `state == 'limited'` (auto-block is meaningless without a Google-side limit to enforce against):

```
[x] Auto-block on overuse
```

`hx-post` to a new endpoint `POST /apps/{package}/auto-block` (form: `child_id`, `enabled: bool`), which upserts the `AppConfig` row (get by `(child_id, package_name)` or create) and returns the updated `app_row.html` partial — identical shape to `set_limit`/`block_app`/`allow_app` in `apps.py`.

### Bonus time (`routers/apps.py`, `templates/partials/app_row.html`)

Mirrors the existing Linux machine bonus feature (`linux_machines.py`'s `/bonus` endpoint, `+15/+30/+60 min` buttons).

`POST /apps/{package}/bonus` — form fields `child_id`, `minutes: int` (accepted values: 15, 30, 60):
1. Get or create the `AppConfig` row for `(child_id, package_name)`.
2. If `bonus_date != today`: `bonus_mins = minutes`, `bonus_date = today` (fresh start each day). Else: `bonus_mins += minutes`.
3. If `auto_blocked_at is not None`: read the app's live `daily_usage_limit_mins` from `svc.get_apps_and_usage(child_id)`, call `svc.set_app_limit(package_name, daily_usage_limit_mins + bonus_mins, child_id)` to unblock immediately, clear `auto_blocked_at = None`.
4. Write `AuditLog(action='bonus_app', child_id=child_id, target=package_name, new_value=str(minutes))`.
5. Return the updated `app_row.html` partial.

Buttons `[+15 min] [+30 min] [+60 min]` are shown in `app_row.html` only when the row's `auto_blocked_at is not None` (i.e. the enforcer, not the parent, put it in this state) — a manually-blocked app already has its own unblock controls (`set_limit`/`allow_app`), no need to duplicate. `apps_page()`'s per-app context therefore also needs `auto_blocked_at` (or a derived `auto_blocked: bool`) alongside `auto_block_enabled`.

## Error Handling

- Google API failures during a poll cycle: caught in `enforce_child`, logged, retried next cycle — no state change, no crash of the loop (matches `linux_poller.py`'s `except Exception` around SSH calls).
- If `block_app` succeeds but the `AuditLog`/`auto_blocked_at` write fails (DB error): the next cycle will see usage still over limit and re-issue `block_app` — idempotent, no double-block harm.
- If the enforcer restarts mid-day: `auto_blocked_at` is durable in the DB, so it correctly skips re-blocking an app it already blocked and correctly still restores at midnight.

## Testing

- `tests/server/test_app_enforcer.py` (new): threshold-trigger test (usage crosses limit → `block_app` called once, `AuditLog` written), no-op when under limit, no-op when app has no live Google limit, midnight-restore test, idempotency test (already `auto_blocked_at` set → no duplicate `block_app` call), bonus-raises-effective-limit test, re-block-after-bonus-exceeded test.
- `tests/server/test_routers_apps.py`: extend for the new `/apps/{package}/auto-block` endpoint, the `/apps/{package}/bonus` endpoint (same-day stacking vs next-day fresh start, immediate unblock when currently auto-blocked), and the checkbox/bonus-buttons appearing in `apps_page()` context.
- `tests/server/test_family_link_service.py` (or wherever `FamilyLinkService` is covered): `bypass_cache=True` skips the cache read.

## Files Changed

| Action | Path |
|---|---|
| Create | `alembic/versions/004_auto_block_overused_apps.py` |
| Create | `src/familylink_server/services/app_enforcer.py` |
| Create | `tests/server/test_app_enforcer.py` |
| Modify | `src/familylink_server/db/models.py` — add `auto_block_enabled`, `auto_blocked_at`, `bonus_mins`, `bonus_date` to `AppConfig`, unique constraint |
| Modify | `src/familylink_server/services/family_link.py` — `bypass_cache` param on `get_apps_and_usage` |
| Modify | `src/familylink_server/routers/apps.py` — DB session in `apps_page()`, new `/apps/{package}/auto-block` and `/apps/{package}/bonus` endpoints |
| Modify | `src/familylink_server/templates/partials/app_row.html` — auto-block checkbox, bonus buttons |
| Modify | `src/familylink_server/main.py` — start/stop `app_enforcer_loop` in lifespan |
| Modify | `tests/server/test_routers_apps.py` — auto-block endpoint + checkbox tests |

## Out of Scope

- Configuring which apps are eligible via a global/env predefined list — opt-in is per child+app via the UI checkbox, not a hardcoded package list.
- Wiring up `AppConfig.max_mins`/`days_mask`/`time_range`/`always_allowed`/`blocked` (pre-existing unused columns) — untouched by this feature.
- Notifying the child that they were auto-blocked.
- Configurable poll interval or configurable grace/overage window (fixed at 5 min).
- Bot/Discord slash command to toggle auto-block or grant bonus (web UI only for now).
- Capping how many times bonus can stack in a day (same as the existing Linux bonus feature — repeated grants just keep adding).
- Notifying the child that bonus time was granted.
