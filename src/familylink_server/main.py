"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from familylink_server.auth.oauth import router as auth_router
from familylink_server.config import settings
from familylink_server.routers.apps import router as apps_router
from familylink_server.routers.devices import router as devices_router
from familylink_server.routers.members import router as members_router
from familylink_server.routers.usage import router as usage_router
from familylink_server.services.family_link import init_service


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize the FamilyLink service singleton at startup."""
    init_service()
    yield


app = FastAPI(
    title="FamilyLink",
    description="Google Family Link management web service",
    lifespan=lifespan,
)

# Add middleware for OAuth session support (must be before routes)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

app.include_router(auth_router)
app.include_router(apps_router)
app.include_router(members_router)
app.include_router(usage_router)
app.include_router(devices_router)

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")
