"""FastAPI application factory."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from familylink_server.services.discord_notifier import DiscordNotifier
    from familylink_server.services.family_link import FamilyLinkService

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from familylink import SessionExpiredError
from familylink_server.auth.oauth import router as auth_router
from familylink_server.config import settings
from familylink_server.routers.admin import router as admin_router
from familylink_server.routers.apps import router as apps_router
from familylink_server.routers.dashboard import router as dashboard_router
from familylink_server.routers.devices import router as devices_router
from familylink_server.routers.history import router as history_router
from familylink_server.routers.linux_machines import router as linux_machines_router
from familylink_server.routers.members import router as members_router
from familylink_server.routers.usage import router as usage_router
from familylink_server.services.family_link import get_service, init_service
from familylink_server.services.linux_poller import poller_loop

logger = logging.getLogger(__name__)


async def health_check_loop(
    service: 'FamilyLinkService',
    notifier: 'DiscordNotifier | None',
    interval: int = 1800,
) -> None:
    """Probe the Family Link API every `interval` seconds; alert Discord on failure."""
    _alert_active = False
    while True:
        await asyncio.sleep(interval)
        try:
            await service.get_members()
            if _alert_active:
                _alert_active = False
                service.set_auth_failed(False)
                if notifier:
                    await notifier.notify_session_restored()
        except SessionExpiredError as exc:
            logger.warning('Health check: session expired — %s', exc)
            if not _alert_active:
                _alert_active = True
                service.set_auth_failed(True)
                if notifier:
                    await notifier.notify_session_expired()
                if await _try_auto_refresh(service, notifier):
                    _alert_active = False
        except Exception as exc:
            logger.warning(
                'Health check probe error (transient, not alerting): %s', exc
            )


async def _try_auto_refresh(
    service: 'FamilyLinkService',
    notifier: 'DiscordNotifier | None',
) -> bool:
    """Call cookie-refresher sidecar; hot-reload service. Returns True on success."""
    url = settings.cookie_refresher_url
    if not url:
        return False
    try:
        logger.info('Auto-refresh: calling sidecar at %s/refresh', url)
        headers = {}
        if settings.refresher_api_key:
            headers['X-Api-Key'] = settings.refresher_api_key
        async with httpx.AsyncClient() as client:
            resp = await client.post(f'{url}/refresh', timeout=120, headers=headers)
            resp.raise_for_status()
        cookies_b64 = resp.json()['cookies_b64']
        service.reinit_with_cookies_b64(cookies_b64)
        if notifier:
            await notifier.notify_session_restored()
        logger.info('Auto-refresh: success')
        return True
    except Exception as exc:
        logger.error('Auto-refresh: failed — %s', exc)
        return False


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize services at startup; shut down cleanly."""
    init_service()

    from familylink_server.db.session import make_session as _make_session

    notifier = None
    bot_task: asyncio.Task | None = None
    if settings.discord_enabled:
        from familylink_server.bot.client import FamilyLinkBot, _bot_task_with_restart
        from familylink_server.services.discord_notifier import init_notifier

        notifier = init_notifier(settings.discord_channel_id)  # type: ignore[arg-type]
        bot = FamilyLinkBot(
            service=get_service(),
            notifier=notifier,
            guild_id=settings.discord_guild_id,  # type: ignore[arg-type]
            summary_time=settings.discord_summary_time_parsed,
            make_session=_make_session,
        )
        bot_task = asyncio.create_task(
            _bot_task_with_restart(bot, settings.discord_bot_token)  # type: ignore[arg-type]
        )
        logger.info('Discord bot task started')
    else:
        logger.info(
            'Discord bot disabled (DISCORD_BOT_TOKEN / GUILD_ID / CHANNEL_ID not set)'
        )

    poller_task = asyncio.create_task(poller_loop(notifier=notifier))
    logger.info('Linux machine poller started')

    health_task = asyncio.create_task(health_check_loop(get_service(), notifier))
    logger.info('Health check task started (interval=1800s)')

    yield

    poller_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller_task

    health_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await health_task

    if bot_task is not None:
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task


app = FastAPI(
    title='FamilyLink',
    description='Google Family Link management web service',
    lifespan=lifespan,
)

app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)


@app.exception_handler(SessionExpiredError)
async def session_expired_handler(
    request: Request, exc: SessionExpiredError
) -> HTMLResponse:
    """Return a 503 page with re-export instructions when Google cookies expire."""
    return HTMLResponse(
        status_code=503,
        content="""<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Session Expired — Family Link</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
</head>
<body>
  <main class="container" style="max-width:600px;margin-top:4rem">
    <article>
      <header><strong>Google session expired</strong></header>
      <p>The Family Link session has expired and needs a full re-export of your Google cookies to restore access.</p>

      <p>If the <code>cookie-refresher</code> sidecar is configured, it will retry automatically on the next health check (every 30 minutes) — no action needed.</p>

      <details open style="margin-top:1rem">
        <summary>Manual fix (CLI, requires restart)</summary>
        <pre>familylink export-cookies --browser chrome --base64 --coolify --restart</pre>
        <p>Run this from a machine signed into the parent Google account in Chrome.</p>
      </details>
    </article>
  </main>
</body>
</html>""",
    )


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(dashboard_router)
app.include_router(history_router)
app.include_router(apps_router)
app.include_router(members_router)
app.include_router(usage_router)
app.include_router(devices_router)
app.include_router(linux_machines_router)

_static = Path(__file__).parent / 'static'
if _static.exists():
    app.mount('/static', StaticFiles(directory=str(_static)), name='static')
