"""FastAPI application factory."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from familylink import SessionExpiredError
from familylink_server.auth.oauth import router as auth_router
from familylink_server.config import settings
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
        logger.info("Discord bot task started")
    else:
        logger.info(
            "Discord bot disabled (DISCORD_BOT_TOKEN / GUILD_ID / CHANNEL_ID not set)"
        )

    poller_task = asyncio.create_task(poller_loop(notifier=notifier))
    logger.info("Linux machine poller started")

    yield

    poller_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller_task

    if bot_task is not None:
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task


app = FastAPI(
    title="FamilyLink",
    description="Google Family Link management web service",
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
      <p>The Family Link cookies have expired. Re-export them and update
      <code>FAMILYLINK_COOKIES_B64</code> in your deployment.</p>
      <pre>familylink export-cookies --base64</pre>
      <p>Then paste the output as the <code>FAMILYLINK_COOKIES_B64</code> environment
      variable in Coolify and redeploy.</p>
    </article>
  </main>
</body>
</html>""",
    )


app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(history_router)
app.include_router(apps_router)
app.include_router(members_router)
app.include_router(usage_router)
app.include_router(devices_router)
app.include_router(linux_machines_router)

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")
