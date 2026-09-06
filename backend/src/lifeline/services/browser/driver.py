"""The Playwright-specific half of browser control.

Confined to this module, behind the protocols the manager depends on, so that everything
around it — process supervision, session lifetime, the verdict logic — can be tested
without a browser on disk. Playwright is imported inside the functions that need it, so a
deployment that only ever imports cookies by hand never loads it.
"""

import logging
import os
from pathlib import Path
from typing import Any, Protocol

from ..cookies import StorageState

logger = logging.getLogger(__name__)

# The screen the interactive login is rendered on. Wide enough for a login form with a
# consent banner over it, small enough to send over a home upload.
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800

# Chromium is told to keep its own crash and first-run furniture out of the way: an
# interactive login is hard enough without a "restore pages?" bar over the form.
LAUNCH_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    "--disable-infobars",
    "--hide-crash-restore-bubble",
    # Chromium's sandbox needs privileges a hardened container does not grant; the browser
    # is already the only thing in this container that touches untrusted pages.
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


class InteractiveBrowser(Protocol):
    """A browser a person is driving through the VNC stream."""

    async def storage_state(self) -> StorageState: ...
    async def user_agent(self) -> str | None: ...
    async def close(self) -> None: ...


class PageResult(Protocol):
    """What a headless navigation produced."""

    status_code: int
    final_url: str
    body: str
    state: StorageState


class Driver(Protocol):
    """Opens browsers, headful for a login and headless for a ping."""

    async def open_interactive(
        self, profile_dir: Path, display: str, url: str
    ) -> InteractiveBrowser: ...

    async def fetch(
        self,
        url: str,
        state: StorageState,
        user_agent: str | None,
        *,
        timeout_seconds: float,
    ) -> PageResult: ...


class _PlaywrightBrowser:
    """A headful persistent context, plus the machinery needed to shut it down."""

    def __init__(self, playwright: Any, context: Any) -> None:
        self._playwright = playwright
        self._context = context
        self._observed_user_agent: str | None = None
        # Read from the first request the browser makes rather than by asking the page.
        # Evaluating JavaScript fails outright while a navigation is in flight ("execution
        # context was destroyed"), and during a login the person is navigating constantly —
        # so asking at save time is exactly when it breaks, losing the agent the captured
        # session has to be replayed with.
        context.on("request", self._remember_user_agent)

    def _remember_user_agent(self, request: Any) -> None:
        if self._observed_user_agent is None:
            self._observed_user_agent = request.headers.get("user-agent")

    async def storage_state(self) -> StorageState:
        return await self._context.storage_state()

    async def user_agent(self) -> str | None:
        if self._observed_user_agent:
            return self._observed_user_agent
        # Nothing has been requested yet — a browser opened on a site that never loaded. The
        # page can still be asked, and a failure here is not worth losing the session over.
        pages = self._context.pages
        if not pages:
            return None
        try:
            return await pages[0].evaluate("() => navigator.userAgent")
        except Exception:
            logger.warning("could not read the browser's User-Agent", exc_info=True)
            return None

    async def close(self) -> None:
        # Both halves are attempted even if the first fails: leaving the Playwright driver
        # running would leave a node process and a browser behind.
        try:
            await self._context.close()
        finally:
            await self._playwright.stop()


class _PageResult:
    """A plain record of one headless navigation."""

    def __init__(self, status_code: int, final_url: str, body: str, state: StorageState) -> None:
        self.status_code = status_code
        self.final_url = final_url
        self.body = body
        self.state = state


class PlaywrightDriver:
    """Drives Chromium through Playwright."""

    async def open_interactive(
        self, profile_dir: Path, display: str, url: str
    ) -> InteractiveBrowser:
        """Open a headful browser on ``display``, at ``url``.

        A persistent context rather than a fresh one so that a partly finished login — a
        device-trust cookie, a half-completed two-factor enrolment — survives closing the
        panel and coming back to it.
        """
        from playwright.async_api import async_playwright

        profile_dir.mkdir(parents=True, exist_ok=True)
        playwright = await async_playwright().start()
        try:
            context = await playwright.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                args=LAUNCH_ARGS,
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                # The whole environment is passed, not just DISPLAY: Playwright replaces the
                # browser's environment with whatever is given here, and a Chromium started
                # without PATH or HOME fails in ways that report only that it closed.
                env={**os.environ, "DISPLAY": display},
            )
        except BaseException:
            await playwright.stop()
            raise

        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception:
            # A site that is slow or refuses the first request should still leave a usable
            # browser on screen — the person can navigate it themselves.
            logger.warning("could not open %s automatically", url, exc_info=True)
        return _PlaywrightBrowser(playwright, context)

    async def fetch(
        self,
        url: str,
        state: StorageState,
        user_agent: str | None,
        *,
        timeout_seconds: float,
    ) -> PageResult:
        """Load ``url`` headlessly with ``state``, and report what came back."""
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        try:
            # The full browser in headless mode, rather than Playwright's separate headless
            # shell: an interactive login needs the full build anyway, and asking for it here
            # too means the image ships one Chromium instead of two — a third of a gigabyte
            # for a second copy that only differs in how it draws.
            browser = await playwright.chromium.launch(
                headless=True, channel="chromium", args=LAUNCH_ARGS
            )
            try:
                context = await browser.new_context(
                    storage_state=state, user_agent=user_agent or None
                )
                page = await context.new_page()
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000
                )
                return _PageResult(
                    status_code=response.status if response else 0,
                    final_url=page.url,
                    body=await page.content(),
                    state=await context.storage_state(),
                )
            finally:
                await browser.close()
        finally:
            await playwright.stop()
