"""Owning the lifetime of an interactive login session."""

import asyncio
import logging
import secrets
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from ...config import Settings
from ..cookies import StorageState
from . import supervisor
from .driver import VIEWPORT_HEIGHT, VIEWPORT_WIDTH, Driver, InteractiveBrowser, PlaywrightDriver


class Processes(Protocol):
    """The process supervision this manager needs.

    Injectable so that the session lifetime — one at a time, idle expiry, teardown ordering
    — can be tested without starting a real X server, which a test host has no reason to
    have and which would leak if a test failed halfway.
    """

    async def start(
        self, name: str, argv: list[str], marker: str, **kwargs: object
    ) -> supervisor.ManagedProcess: ...

    async def stop(self, managed: supervisor.ManagedProcess) -> None: ...

    async def reap(self, *markers: str) -> int: ...

    async def wait_for_display(self, display: str, timeout: float = 10.0) -> None: ...

logger = logging.getLogger(__name__)

# The longest a login session may live even while someone is watching it. The idle timeout
# cannot end a session that has a viewer — a tab left open is not an abandoned session, and
# closing one mid-login would lose the work — so this is what stops a forgotten tab holding
# a browser and an X server indefinitely.
MAX_SESSION_LIFETIME = timedelta(hours=4)


class BrowserUnavailable(RuntimeError):
    """The deployment cannot open a browser."""


class NoSuchLoginSession(LookupError):
    """The referenced login session is not open."""


@dataclass
class LoginSession:
    """One person's browser, on its own X display, being streamed to their tab."""

    site_id: int
    # Bearer of the VNC stream's URL. The stream is a live, already-logged-in browser, so
    # its address is an unguessable token rather than the site's id.
    token: str
    display: str
    rfb_port: int
    browser: InteractiveBrowser
    processes: list[supervisor.ManagedProcess]
    profile_dir: Path
    idle_timeout: timedelta
    expires_at: datetime
    hard_deadline: datetime
    # How many browser tabs are streaming this session. A session with a viewer is in use.
    viewers: int = 0
    watchdog: asyncio.Task[None] | None = field(default=None, repr=False)


def _free_port() -> int:
    """A port nothing is listening on, bound to the loopback interface only."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class BrowserManager:
    """Starts, streams and stops the browser used for interactive logins.

    One session at a time. A headful browser and an X server are the most expensive thing
    this application does, and a second one buys nothing: a person can only log into one
    site at a time.
    """

    def __init__(
        self,
        settings: Settings,
        driver: Driver | None = None,
        processes: Processes | None = None,
    ) -> None:
        self._settings = settings
        self._driver = driver or PlaywrightDriver()
        self._processes: Processes = processes or supervisor
        self._active: LoginSession | None = None
        # Serialises open and close: two requests arriving together would otherwise both
        # start an X server on the same display.
        self._lock = asyncio.Lock()

    @property
    def active(self) -> LoginSession | None:
        """The open session, if there is one."""
        return self._active

    @property
    def profile_dir(self) -> Path:
        """Where the login browser keeps its profile.

        One profile for every site rather than one each. A browser extension lives in the
        profile, so a profile per site meant a password manager had to be installed, permitted,
        signed into and two-factored again for every site added — which costs more than typing
        the password it was there to avoid, and sends a new-device warning each time.

        Nothing depends on the separation: a captured session is stored in the database, and a
        browser-mode ping builds a throwaway context from that rather than from this profile.
        """
        return self._settings.profiles_dir / "login-browser"

    async def reap_orphans(self) -> int:
        """Kill anything left over from a previous run.

        A container that was killed rather than shut down leaves an X server and a browser
        holding a profile directory, which stops the next login from opening it.
        """
        return await self._processes.reap(
            str(self._settings.profiles_dir),
            # The trailing space is the argument boundary: without it, display :99's marker
            # also matches an X server running on :991.
            f"Xvfb :{self._settings.display_base} ",
        )

    async def open_login(
        self, site_id: int, url: str, idle_timeout: timedelta, *, signed_out: bool = False
    ) -> LoginSession:
        """Start a browser for ``site_id`` and stream its screen.

        Opening a session closes any other: the alternative is refusing, which would leave
        someone stuck behind a panel they had already finished with.

        ``signed_out`` empties the shared profile's cookie jar first. Asked for when the site has
        no session yet, where landing on a page already signed in as somebody else is both
        confusing and a way to capture the wrong account without noticing — a second account on
        a site already logged into in this browser being the case that matters. The extension's
        own state is not kept in cookies, so it survives.
        """
        if not self._settings.browser_enabled:
            raise BrowserUnavailable("browser sessions are disabled in this deployment")

        async with self._lock:
            await self._close_locked()
            display = f":{self._settings.display_base}"
            profile_dir = self.profile_dir
            rfb_port = _free_port()
            processes: list[supervisor.ManagedProcess] = []
            try:
                processes.append(
                    await self._processes.start(
                        "Xvfb",
                        [
                            "Xvfb",
                            display,
                            "-screen",
                            "0",
                            f"{VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}x24",
                            "-nolisten",
                            "tcp",
                        ],
                        marker=f"Xvfb {display} ",
                    )
                )
                await self._processes.wait_for_display(display)
                processes.append(
                    await self._processes.start(
                        "x11vnc",
                        [
                            "x11vnc",
                            "-display",
                            display,
                            "-rfbport",
                            str(rfb_port),
                            # Reachable only from inside the container: the API bridges the
                            # stream, so nothing outside ever needs the RFB port. No password
                            # is set because nothing can dial it directly.
                            "-localhost",
                            "-nopw",
                            "-forever",
                            "-shared",
                            "-noxdamage",
                            "-quiet",
                        ],
                        marker=f"-rfbport {rfb_port}",
                    )
                )
                browser = await self._driver.open_interactive(
                    profile_dir,
                    display,
                    url,
                    self._settings.browser_extension_dir,
                    signed_out=signed_out,
                )
            except BaseException:
                # A half-started session must not be left holding a display or a port.
                for process in processes:
                    await self._processes.stop(process)
                raise

            opened_at = datetime.now(UTC)
            session = LoginSession(
                site_id=site_id,
                token=secrets.token_urlsafe(24),
                display=display,
                rfb_port=rfb_port,
                browser=browser,
                processes=processes,
                profile_dir=profile_dir,
                idle_timeout=idle_timeout,
                expires_at=opened_at + idle_timeout,
                hard_deadline=opened_at + max(MAX_SESSION_LIFETIME, idle_timeout),
            )
            session.watchdog = asyncio.create_task(
                self._expire(session), name=f"login-timeout-{site_id}"
            )
            self._active = session
            return session

    def get(self, token: str) -> LoginSession:
        """The open session with this token."""
        session = self._active
        if session is None or not secrets.compare_digest(session.token, token):
            raise NoSuchLoginSession("no such login session")
        return session

    def touch(self, session: LoginSession) -> None:
        """Push back the idle deadline, because someone is still using the session."""
        session.expires_at = datetime.now(UTC) + session.idle_timeout

    def add_viewer(self, session: LoginSession) -> None:
        """Note that a tab has started streaming this session."""
        session.viewers += 1
        self.touch(session)

    def remove_viewer(self, session: LoginSession) -> None:
        """Note that a tab has stopped streaming, and restart the idle clock."""
        session.viewers = max(session.viewers - 1, 0)
        self.touch(session)

    async def capture(self, token: str) -> tuple[StorageState, str | None]:
        """Read the session out of the live browser."""
        session = self.get(token)
        return await session.browser.storage_state(), await session.browser.user_agent()

    async def close(self) -> None:
        """Close the open session, if any."""
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        session = self._active
        if session is None:
            return
        self._active = None
        if session.watchdog is not None:
            session.watchdog.cancel()
        try:
            await session.browser.close()
        except Exception:
            # A browser that will not close cleanly is still going to be killed below; the
            # failure is worth a line in the log, not an aborted teardown.
            logger.warning("the browser did not close cleanly", exc_info=True)
        for process in session.processes:
            await self._processes.stop(process)
        # Playwright's own children are not in any group this owns, so they are matched by
        # the profile directory they were started with.
        await self._processes.reap(str(session.profile_dir))

    async def _expire(self, session: LoginSession) -> None:
        """Close a session that nobody is using any more."""
        try:
            while True:
                now = datetime.now(UTC)
                if now >= session.hard_deadline:
                    break
                # A session being watched is being used; only the hard deadline ends it.
                deadline = session.hard_deadline if session.viewers else session.expires_at
                remaining = (deadline - now).total_seconds()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(remaining, 30))
        except asyncio.CancelledError:
            return
        logger.info("closing the idle login session for site %s", session.site_id)
        # The watchdog is this task; cancelling it from inside _close_locked would cancel
        # the very coroutine doing the closing, so it is detached first.
        session.watchdog = None
        await self.close()

    async def fetch(
        self,
        url: str,
        state: StorageState,
        user_agent: str | None,
        *,
        accept_language: str | None = None,
    ) -> object:
        """Load a page headlessly with a stored session, for a browser-mode ping."""
        if not self._settings.browser_enabled:
            raise BrowserUnavailable("browser checks are disabled in this deployment")
        return await self._driver.fetch(
            url,
            state,
            user_agent,
            timeout_seconds=self._settings.request_timeout_seconds,
            accept_language=accept_language,
        )
