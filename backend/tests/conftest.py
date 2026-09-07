"""Shared fixtures.

Every test runs against its own temporary data directory and its own SQLite file, so no
test can see another's rows and none of them touch a developer's real database.
"""

import asyncio
import tempfile
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from lifeline.config import Settings
from lifeline.db import create_engine, create_sessionmaker
from lifeline.models import (  # noqa: F401 - User is re-exported for fixture annotations
    Base,
    CaptureMethod,
    PingMethod,
    Setting,
    Site,
    SiteSession,
    SiteStatus,
)
from lifeline.services.checker import FetchResult
from lifeline.services.cookies import StorageState
from lifeline.services.crypto import Cipher
from lifeline.services.notifier import Notifier
from lifeline.services.runner import CheckRunner


@pytest.fixture
def data_dir() -> Iterator[Path]:
    """A throwaway data directory."""
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory)


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    """Settings pointed at the throwaway directory, with the scheduler off.

    The scheduler is disabled because a test drives the checker directly; a background
    loop would otherwise race with the assertions and make failures depend on timing.
    """
    return Settings(
        data_dir=data_dir,
        secret_key="test-secret-key",
        scheduler_enabled=False,
        setup_token="test-setup-token",
        # Deliberately not the default. The lifespan test builds the real service graph, which
        # reaps leftover processes by matching "Xvfb :<display_base>" against every command line
        # on the machine — so with the default it would find and kill the X server the
        # interactive-login tests are running on.
        display_base=901,
    )


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """An engine with the schema created directly from the models.

    ``create_all`` rather than running the migrations: this asserts against the schema the
    code expects, and a separate test checks that the migrations still produce it.
    """
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """A session factory bound to the test engine."""
    return create_sessionmaker(engine)


@pytest.fixture
async def db(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """A session for tests that talk to the database directly."""
    async with sessionmaker() as session:
        yield session


@pytest.fixture
def cipher(settings: Settings) -> Cipher:
    """A cipher using the test secret."""
    return Cipher.from_settings(settings)


class RecordingSender:
    """A notification sender that keeps what it was asked to send.

    Standing in for Apprise here is deliberate: the assertions are about which messages
    the rules produce, and a real send would make that depend on a network.
    """

    def __init__(self, *, delivers: bool = True) -> None:
        self.delivers = delivers
        self.sent: list[tuple[list[str], str, str]] = []

    async def send(self, urls: list[str], title: str, body: str) -> bool:
        self.sent.append((urls, title, body))
        return self.delivers

    @property
    def titles(self) -> list[str]:
        return [title for _, title, _ in self.sent]


class StubFetcher:
    """A fetcher returning a queued response, or raising a queued error."""

    def __init__(self, *results: FetchResult | Exception) -> None:
        self._results: list[FetchResult | Exception] = list(results)
        self.calls: list[tuple[Site, StorageState]] = []

    async def fetch(self, site: Site, state: StorageState) -> FetchResult:
        self.calls.append((site, state))
        result = self._results.pop(0) if len(self._results) > 1 else self._results[0]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def sender() -> RecordingSender:
    """The notification sender under the notifier."""
    return RecordingSender()


@pytest.fixture
def notifier(sender: RecordingSender) -> Notifier:
    """A notifier that records instead of sending."""
    return Notifier(sender)


def make_site(**overrides: object) -> Site:
    """A site with the defaults a check needs, overridable per test."""
    values: dict[str, object] = {
        "id": 1,
        "name": "example",
        "ping_url": "https://example.org/home",
        "enabled": True,
        "interval_days": 7,
        "jitter_percent": 0,
        "ping_method": PingMethod.HTTP,
        "expected_status": 200,
        "follow_redirects": True,
        "status": SiteStatus.UNKNOWN,
        "consecutive_failures": 0,
    }
    values.update(overrides)
    return Site(**values)


def make_settings(**overrides: object) -> Setting:
    """A settings row with the model's defaults already applied.

    A ``Setting()`` built in Python has ``None`` in every column: SQLAlchemy applies
    column defaults when the row is inserted, not when the object is constructed. Tests
    that pass one to a pure function therefore need the values filled in explicitly, and
    test_defaults_match_the_model keeps this list honest.
    """
    values: dict[str, object] = {
        "apprise_urls": "",
        "notify_on_lapsed": True,
        "notify_on_recovered": True,
        "notify_on_errors": True,
        "notify_on_cookie_expiry": True,
        "notify_on_deadline": True,
        "notify_cooldown_hours": 24,
        "warning_lead_days": 7,
        "error_threshold": 3,
        "log_level": "INFO",
        "default_interval_days": 7,
        "retention_days": 90,
        "browser_idle_timeout_minutes": 15,
    }
    values.update(overrides)
    return Setting(**values)


def make_fetch_result(**overrides: object) -> FetchResult:
    """A successful fetch, overridable per test."""
    values: dict[str, object] = {
        "status_code": 200,
        "final_url": "https://example.org/home",
        "body": "<html>Logged in as jure. Log out</html>",
        "state": SAMPLE_STATE,
        "rotated": False,
    }
    values.update(overrides)
    return FetchResult(**values)


SAMPLE_STATE: StorageState = {
    "cookies": [
        {
            "name": "session",
            "value": "abc",
            "domain": ".example.org",
            "path": "/",
            "expires": 4102444800.0,
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        }
    ],
    "origins": [],
}


@pytest.fixture
async def site(db: AsyncSession) -> Site:
    """A persisted site with no session captured."""
    row = make_site(id=None)
    db.add(row)
    await db.commit()
    return row


@pytest.fixture
async def logged_in_site(db: AsyncSession, cipher: Cipher, site: Site) -> Site:
    """A persisted site with a stored session."""
    site.session = SiteSession(
        site_id=site.id,
        state=cipher.encrypt_json(SAMPLE_STATE),
        captured_via=CaptureMethod.BROWSER,
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await db.commit()
    return site


@pytest.fixture
def make_runner(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    cipher: Cipher,
    notifier: Notifier,
) -> "Callable[..., CheckRunner]":
    """Build a runner whose fetcher returns the given results."""

    def build(*results: FetchResult | Exception) -> CheckRunner:
        fetcher = StubFetcher(*(results or (make_fetch_result(),)))
        return CheckRunner(
            sessionmaker, settings, cipher, notifier, {PingMethod.HTTP: fetcher}
        )

    return build


@dataclass
class FakeProcess:
    """Stands in for a supervised child process."""

    name: str
    argv: list[str]
    marker: str
    stopped: bool = False


class FakeProcesses:
    """Records what would have been started, and what was stopped.

    An interactive login needs an X server and a VNC server; starting real ones in a test
    would leak them on a failure, which is the exact problem the supervisor exists to solve.
    """

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.started: list[FakeProcess] = []
        self.reaped: list[tuple[str, ...]] = []
        self.displays_waited: list[str] = []
        self.fail_on = fail_on

    async def start(self, name: str, argv: list[str], marker: str, **_: object) -> FakeProcess:
        if name == self.fail_on:
            raise OSError(f"{name} refused to start")
        process = FakeProcess(name=name, argv=argv, marker=marker)
        self.started.append(process)
        return process

    async def stop(self, managed: FakeProcess) -> None:
        managed.stopped = True

    async def reap(self, *markers: str) -> int:
        self.reaped.append(markers)
        return 0

    async def wait_for_display(self, display: str, timeout: float = 10.0) -> None:
        self.displays_waited.append(display)

    @property
    def running(self) -> list[FakeProcess]:
        return [process for process in self.started if not process.stopped]


class FakeBrowser:
    """A stand-in for the headful browser a person logs in through."""

    def __init__(self, state: StorageState | None = None, user_agent: str = "FakeAgent/1") -> None:
        self._state = state or SAMPLE_STATE
        self._user_agent = user_agent
        self.closed = False

    async def storage_state(self) -> StorageState:
        return self._state

    async def user_agent(self) -> str:
        return self._user_agent

    async def close(self) -> None:
        self.closed = True


class FakeDriver:
    """A driver that hands out FakeBrowsers instead of launching Chromium."""

    def __init__(self, *, fail: bool = False) -> None:
        self.opened: list[tuple[Path, str, str]] = []
        self.fetched: list[str] = []
        self.browser = FakeBrowser()
        self.fail = fail

    async def open_interactive(self, profile_dir: Path, display: str, url: str) -> FakeBrowser:
        if self.fail:
            raise RuntimeError("the browser would not start")
        self.opened.append((profile_dir, display, url))
        return self.browser

    async def fetch(
        self, url: str, state: StorageState, user_agent: str | None, *, timeout_seconds: float
    ) -> object:
        self.fetched.append(url)

        class Result:
            status_code = 200
            final_url = url
            body = "<html>Logged in as jure</html>"

        result = Result()
        result.state = state
        return result


@pytest.fixture
def fake_processes() -> FakeProcesses:
    """The stand-in process supervisor."""
    return FakeProcesses()


@pytest.fixture
def fake_driver() -> FakeDriver:
    """The stand-in browser driver."""
    return FakeDriver()


@pytest.fixture
def browser(settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses):
    """A browser manager that starts nothing real."""
    from lifeline.services.browser.manager import BrowserManager

    return BrowserManager(settings, fake_driver, fake_processes)


@pytest.fixture
def services(
    settings: Settings,
    engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    cipher: Cipher,
    notifier: Notifier,
    browser,
):
    """The service graph, with every outside edge replaced by a stand-in."""
    from lifeline.api.deps import Services
    from lifeline.api.security import LoginThrottle, SessionCookies
    from lifeline.services.browser.fetcher import BrowserFetcher
    from lifeline.services.scheduler import Scheduler

    fetchers = {
        PingMethod.HTTP: StubFetcher(make_fetch_result()),
        PingMethod.BROWSER: BrowserFetcher(browser),
    }
    runner = CheckRunner(sessionmaker, settings, cipher, notifier, fetchers)
    return Services(
        settings=settings,
        engine=engine,
        sessionmaker=sessionmaker,
        cipher=cipher,
        notifier=notifier,
        runner=runner,
        scheduler=Scheduler(sessionmaker, settings, runner, notifier),
        cookies=SessionCookies(settings.secret_key, timedelta(hours=1)),
        throttle=LoginThrottle(settings.login_rate_limit_per_minute),
        browser=browser,
    )


@pytest.fixture
def app(services):
    """The application, wired to the test services.

    Built without running its lifespan: the lifespan would construct a second, real service
    graph — its own engine, its own encryption key, a live scheduler — and then the test
    would be asserting against services nothing under test is using.
    """
    from lifeline.api.app import create_app

    application = create_app(services.settings)
    application.state.services = services
    application.state.setup_token = services.settings.setup_token
    return application


@pytest.fixture
async def client(app) -> AsyncIterator["httpx.AsyncClient"]:
    """An HTTP client speaking to the application in-process."""
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://lifeline.test") as instance:
        yield instance


@pytest.fixture
async def admin(db: AsyncSession) -> "User":
    """An administrator, so the instance counts as set up."""
    from lifeline.api.security import hash_password
    from lifeline.models import User

    user = User(username="jure", password_hash=hash_password("a-good-long-password"))
    db.add(user)
    await db.commit()
    return user


@pytest.fixture
async def logged_in(client, services, admin) -> "httpx.AsyncClient":
    """A client carrying a valid session cookie."""
    client.cookies.set(
        services.settings.session_cookie_name, services.cookies.issue(admin.id)
    )
    return client


class EchoServer:
    """A TCP server standing in for x11vnc, torn down deterministically.

    Every accepted connection is remembered and closed on exit, rather than left for the event
    loop to drop when the test ends. A transport finalised by the garbage collector instead of
    being closed raises ResourceWarning, and since this suite treats warnings as errors that
    surfaced as an unrelated test failing every few runs.

    A connection is recorded when its handler runs, which is not guaranteed to have happened by
    the time a test that never reads anything finishes — so read at least one byte before leaving
    the block. That also makes such a test assert something worth asserting.
    """

    def __init__(self, greeting: bytes = b"", hang_up: bool = False) -> None:
        self._greeting = greeting
        self._hang_up = hang_up
        self._writers: list[asyncio.StreamWriter] = []
        self._server: asyncio.Server | None = None
        self.port = 0

    async def __aenter__(self) -> "EchoServer":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_: object) -> None:
        for writer in self._writers:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                # The peer is already gone; there is nothing left to close cleanly.
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.append(writer)
        if self._hang_up:
            # Closed here rather than by returning: a handler that just returns leaves the
            # connection open, so the other end never sees the hang-up being tested.
            writer.close()
            return
        if self._greeting:
            writer.write(self._greeting)
            await writer.drain()
        while data := await reader.read(1024):
            writer.write(b"echo:" + data)
            await writer.drain()
