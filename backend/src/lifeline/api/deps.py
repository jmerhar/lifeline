"""The wiring every request handler draws on."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from jigkit.auth.sessions import SessionStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ..config import Settings
from ..models import User
from ..services.browser.manager import BrowserManager
from ..services.crypto import Cipher
from ..services.detect import Detector
from ..services.notifier import Notifier
from ..services.runner import CheckRunner
from ..services.scheduler import Scheduler
from .security import LoginThrottle, login_sessions

# Returned instead of 401 while the instance has no administrator, so the UI knows to show
# the first-run wizard rather than a login form it cannot get past.
SETUP_REQUIRED_STATUS = status.HTTP_409_CONFLICT
SETUP_REQUIRED_DETAIL = "setup_required"


@dataclass
class Services:
    """Everything built once per application and shared by its handlers."""

    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    cipher: Cipher
    notifier: Notifier
    runner: CheckRunner
    scheduler: Scheduler
    sessions: SessionStore
    throttle: LoginThrottle
    browser: BrowserManager
    detector: Detector
    #: Held while the first-run setup creates the administrator, so two requests at once cannot
    #: both find no administrator and both create one.
    setup_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def get_services(request: Request) -> Services:
    """The services attached to the running application."""
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


async def get_db(services: ServicesDep) -> AsyncIterator[AsyncSession]:
    """A database session that commits when the handler returns without raising."""
    async with services.sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


DbDep = Annotated[AsyncSession, Depends(get_db)]


async def _find_admin(session: AsyncSession) -> User | None:
    result = await session.execute(select(User).order_by(User.id).limit(1))
    return result.scalar_one_or_none()


async def require_setup_complete(db: DbDep) -> None:
    """Refuse ordinary requests until someone has been through the wizard."""
    if await _find_admin(db) is None:
        raise HTTPException(status_code=SETUP_REQUIRED_STATUS, detail=SETUP_REQUIRED_DETAIL)


async def require_user(request: Request, services: ServicesDep, db: DbDep) -> User | None:
    """The logged-in administrator, or a refusal.

    ``auth_disabled`` exists for an instance already behind someone else's authentication;
    it skips the check rather than inventing a user, so nothing downstream can mistake it
    for a real login.
    """
    if await _find_admin(db) is None:
        raise HTTPException(status_code=SETUP_REQUIRED_STATUS, detail=SETUP_REQUIRED_DETAIL)
    if services.settings.auth_disabled:
        return None

    token = request.cookies.get(services.settings.session_cookie_name)
    session = await services.sessions.find(db, token) if token else None
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return session.user


UserDep = Annotated[User | None, Depends(require_user)]


def build_services(settings: Settings) -> Services:
    """Construct the whole object graph for a set of settings."""
    from ..db import create_engine, create_sessionmaker
    from ..models import PingMethod
    from ..services.browser.fetcher import BrowserFetcher
    from ..services.checker import HttpFetcher
    from ..services.notifier import AppriseSender

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    cipher = Cipher.from_settings(settings)
    notifier = Notifier(AppriseSender())
    browser = BrowserManager(settings)
    fetchers = {
        PingMethod.HTTP: HttpFetcher(settings),
        PingMethod.BROWSER: BrowserFetcher(browser),
    }
    runner = CheckRunner(sessionmaker, settings, cipher, notifier, fetchers)
    scheduler = Scheduler(sessionmaker, settings, runner, notifier)
    return Services(
        settings=settings,
        engine=engine,
        sessionmaker=sessionmaker,
        cipher=cipher,
        notifier=notifier,
        runner=runner,
        scheduler=scheduler,
        sessions=login_sessions(settings),
        throttle=LoginThrottle(settings.login_rate_limit_per_minute),
        browser=browser,
        detector=Detector(settings, browser),
    )
