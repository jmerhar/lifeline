"""The wiring every request handler draws on."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
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
from .security import LoginThrottle, SessionCookies

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
    cookies: SessionCookies
    throttle: LoginThrottle
    browser: BrowserManager
    detector: Detector


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
    user_id = services.cookies.read(token) if token else None
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
        )
    user = await db.get(User, user_id)
    if user is None:
        # The cookie is valid but its user is gone; treat it as no cookie at all.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
        )
    return user


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
        cookies=SessionCookies(
            cipher_secret(settings), timedelta(hours=settings.session_lifetime_hours)
        ),
        throttle=LoginThrottle(settings.login_rate_limit_per_minute),
        browser=browser,
        detector=Detector(settings, browser),
    )


def cipher_secret(settings: Settings) -> str:
    """The secret the session cookie is signed with.

    The same secret as the session store uses: rotating it invalidates browser logins and
    stored sessions together, which is the honest behaviour — both were protected by it.
    """
    from ..services.crypto import load_or_create_secret

    return load_or_create_secret(settings)
