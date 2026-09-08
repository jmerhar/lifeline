"""The application factory."""

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import SETUP_TOKEN_DISABLED, Settings, get_settings
from ..services import logs
from .deps import build_services
from .routers import auth, browser, checks, health, settings as settings_router, setup, sites

logger = logging.getLogger(__name__)

API_PREFIX = "/api"


def resolve_setup_token(settings: Settings) -> str | None:
    """The token the first-run wizard will demand, or None if it is switched off.

    Generated when none is configured, so an instance reachable from the internet before
    anyone has set it up cannot be claimed by whoever finds the URL first. It is not
    persisted: a restart before setup is a fine moment to mint a new one, and after setup it
    is never needed again.
    """
    if settings.setup_token == SETUP_TOKEN_DISABLED:
        return None
    return settings.setup_token or secrets.token_urlsafe(9)


async def setup_is_pending(services: object) -> bool:
    """Whether this instance still has no administrator.

    Read once at startup to decide whether a setup token is needed at all. An unreadable
    database is treated as pending: minting a token the wizard will reject costs nothing,
    whereas skipping it would leave the wizard unguarded if the database turns out to be
    empty.
    """
    from sqlalchemy import func, select
    from sqlalchemy.exc import SQLAlchemyError

    from ..models import User

    try:
        async with services.sessionmaker() as session:  # type: ignore[attr-defined]
            count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    except SQLAlchemyError:
        return True
    return count == 0


def _announce(token: str | None) -> None:
    if token is None:
        logger.warning(
            "the first-run wizard is unguarded (SETUP_TOKEN=%s); do not expose this "
            "instance until an administrator has been created",
            SETUP_TOKEN_DISABLED,
        )
        return
    # Deliberately loud and easy to copy: this is the one secret a new deployment has to
    # find, and it is only ever printed here.
    logger.info("=" * 72)
    logger.info("first-run setup token: %s", token)
    logger.info("open the web interface and use it to create the administrator account")
    logger.info("=" * 72)


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
        # Only while there is nobody to log in as. Printing it on every restart of a
        # configured instance puts a live-looking secret in the log for no reason, and trains
        # whoever reads that log to ignore the one time it matters.
        if await setup_is_pending(services):
            app.state.setup_token = resolve_setup_token(settings)
            _announce(app.state.setup_token)
        else:
            app.state.setup_token = None
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

    for module in (health, setup, auth, sites, checks, settings_router, browser):
        app.include_router(module.router, prefix=API_PREFIX)

    _mount_frontend(app, settings)
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


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the built single-page app, when one is present.

    Absent — which is how the dev stack runs, with Vite serving the app and proxying the
    API — the application is just the API, and nothing here pretends otherwise.
    """
    directory = settings.static_dir
    if directory is None or not directory.is_dir():
        logger.info("no built frontend at %s; serving the API only", directory)
        return

    index = directory / "index.html"
    app.mount("/assets", StaticFiles(directory=directory / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """Serve a real file if there is one, and the app's shell otherwise.

        Client-side routing means /sites and /settings are not files: they have to return
        the shell so the app can read the URL and render the right view. Registered last, so
        every API route is matched before this catch-all sees the request.
        """
        candidate = (directory / path).resolve()
        # Confining the result to the static directory keeps a crafted path such as
        # ../../etc/passwd from being served.
        if path and directory.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)
