"""The application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from jigkit.web import (
    health_router,
    install_security_headers,
    install_write_guard,
    mount_spa,
)
from sqlalchemy import text

from .. import __version__
from ..config import Settings, get_settings
from ..services import logs
from .deps import build_services
from .routers import auth, browser, checks, setup, sites
from .routers import settings as settings_router

logger = logging.getLogger(__name__)

API_PREFIX = "/api"
#: The value of the X-Requested-With header every write must carry; the interface sends it.
WRITE_HEADER_VALUE = "lifeline"


async def check_database(request: Request) -> None:
    """Run a trivial query, raising if the database cannot answer."""
    async with request.app.state.services.engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application."""
    settings = settings or get_settings()
    # The configured level is the bootstrap one: it applies until the settings row can be read,
    # at which point the stored level takes over.
    log_file = logs.configure(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = build_services(settings)
        app.state.services = services
        if log_file is not None:
            logger.info("logging to %s", log_file)
        await _apply_stored_log_level(services)
        # A container that was killed rather than shut down leaves an X server and a browser
        # holding a profile directory, which stops the next login from opening it.
        await services.browser.reap_orphans()
        services.scheduler.start()
        try:
            yield
        finally:
            # Ordered: stop scheduling work, end the browser, then close the database the
            # other two were using.
            await services.scheduler.stop()
            await services.browser.close()
            await services.engine.dispose()

    app = FastAPI(
        title="lifeline",
        summary="Keep logged-in website sessions alive with scheduled pings",
        version=__version__,
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )

    app.include_router(
        health_router(check_database, version=__version__, revision=settings.revision),
        prefix=API_PREFIX,
    )
    for module in (setup, auth, sites, checks, settings_router, browser):
        app.include_router(module.router, prefix=API_PREFIX)
    install_write_guard(
        app, value=WRITE_HEADER_VALUE, public_url=settings.public_url, prefix=API_PREFIX
    )
    install_security_headers(app)
    # Last: its catch-all answers whatever no route above matched.
    mount_spa(app, settings.static_dir, api_prefix=API_PREFIX)
    return app


async def _apply_stored_log_level(services: object) -> None:
    """Raise or lower the log level to whatever the settings say.

    Best-effort. The configured level already applies, so a database that cannot be read here
    costs some detail in the log — and that is not a reason to refuse to start. Whatever is wrong
    with the database will announce itself through the health endpoint and through every request
    that touches it, which is a far clearer signal than a process that exits at boot.
    """
    from sqlalchemy.exc import SQLAlchemyError

    from ..services.store import load_settings_row

    try:
        async with services.sessionmaker() as session:  # type: ignore[attr-defined]
            row = await load_settings_row(session)
            await session.commit()
    except SQLAlchemyError:
        logger.warning("could not read the stored log level; keeping the configured one")
        return
    logs.apply_level(row.log_level)
