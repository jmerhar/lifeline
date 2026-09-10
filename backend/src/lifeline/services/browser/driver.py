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
from urllib.parse import urlsplit

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


def extension_args(extension_dir: Path | None) -> list[str]:
    """The flags that load an unpacked extension, or none at all.

    Both flags are needed: --load-extension adds this one, and --disable-extensions-except stops
    Chromium loading anything else it finds in the profile. A directory that is not there is
    ignored rather than fatal — the extension is a convenience, and a login must still be possible
    without it.
    """
    if extension_dir is None or not extension_dir.is_dir():
        return []
    path = str(extension_dir)
    return [f"--disable-extensions-except={path}", f"--load-extension={path}"]


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
        self,
        profile_dir: Path,
        display: str,
        url: str,
        extension_dir: Path | None = None,
        *,
        signed_out: bool = False,
    ) -> InteractiveBrowser: ...

    async def fetch(
        self,
        url: str,
        state: StorageState,
        user_agent: str | None,
        *,
        timeout_seconds: float,
        accept_language: str | None = None,
    ) -> PageResult: ...


# How long to let a page finish building itself before reading it. The whole point of a browser
# ping is the document the JavaScript produces, and a framework has to fetch its bundle, decide
# whether there is a session, and route before any of that exists — none of which has happened by
# the time the served markup has parsed.
SETTLE_SECONDS = 15.0

# Two things have to be true before a page is worth reading: it is showing something, and it has
# stopped changing. Either test alone is satisfied by an empty shell — which has no text but is
# perfectly stable, and stops fetching the moment its bundle has arrived — so the wait is for
# both. Counted in polls rather than seconds so a page that renders quickly is not held up.
_SETTLED = """
() => {
  const text = document.body ? document.body.innerText.trim().length : 0;
  const seen = (window.__lifelineSettle ||= { length: -1, unchanged: 0 });
  if (text === 0) { seen.length = -1; seen.unchanged = 0; return false; }
  if (text === seen.length) { seen.unchanged += 1; }
  else { seen.length = text; seen.unchanged = 0; }
  return seen.unchanged >= 2;
}
"""
_POLL_MS = 250


async def _settle(page: Any) -> None:
    """Wait for the page to show something and stop changing, tolerating one that never does.

    A page that animates, polls on a timer or holds a socket open never stops changing, and is
    not broken for it — so the wait is bounded and a timeout is not an error. What it costs in
    that case is the budget above, once, on a check that opted into a browser.
    """
    from playwright.async_api import Error as PlaywrightError

    try:
        await page.wait_for_function(
            _SETTLED, timeout=SETTLE_SECONDS * 1000, polling=_POLL_MS
        )
    except PlaywrightError:
        logger.debug("page never settled; reading it as it stands")


async def forget_site(context: Any, page: Any, url: str) -> None:
    """Leave the browser holding nothing that would sign anybody in to ``url``.

    Cookies are only half of it. A site that builds its page in the browser generally keeps its
    token in local storage instead, and emptying the cookie jar leaves that untouched — so the site
    opens already signed in, which is how somebody else's account gets captured for a new site.

    Everything the origin holds goes: its cookies, both kinds of storage, its databases and caches.
    Only that origin, so nothing belonging to another site in this shared profile is disturbed and
    an extension keeps the setup that was done once for it.
    """
    from playwright.async_api import Error as PlaywrightError

    origin = _origin_of(url)
    if origin is None:
        return
    try:
        session = await context.new_cdp_session(page)
        # Cookies included: asking per-origin covers them, which is why nothing here empties the
        # jar wholesale and logs every other site in this profile out along the way.
        await session.send(
            "Storage.clearDataForOrigin", {"origin": origin, "storageTypes": "all"}
        )
        await session.detach()
    except PlaywrightError:
        # Leaves the browser signed in rather than failing the login outright, since a person is
        # about to look at it and can sign out themselves.
        logger.warning("could not clear stored data for %s", origin, exc_info=True)


def _origin_of(url: str) -> str | None:
    """The scheme and host of ``url``, which is what storage is keyed by."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


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
        self,
        profile_dir: Path,
        display: str,
        url: str,
        extension_dir: Path | None = None,
        *,
        signed_out: bool = False,
    ) -> InteractiveBrowser:
        """Open a headful browser on ``display``, at ``url``.

        A persistent context rather than a fresh one so that a partly finished login — a
        device-trust cookie, a half-completed two-factor enrolment — survives closing the
        panel and coming back to it. It is also what makes an extension loadable at all:
        Chromium only accepts one for a context with a profile on disk.
        """
        from playwright.async_api import async_playwright

        profile_dir.mkdir(parents=True, exist_ok=True)
        playwright = await async_playwright().start()
        try:
            context = await playwright.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                args=[*LAUNCH_ARGS, *extension_args(extension_dir)],
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
        if signed_out:
            # Before navigating, so the site is asked for as somebody with no session.
            await forget_site(context, page, url)

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
        accept_language: str | None = None,
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
                    storage_state=state,
                    user_agent=user_agent or None,
                    # A header on the context rather than on the request, so it is sent by every
                    # navigation the page makes on its own as well as by the first one.
                    extra_http_headers=(
                        {"Accept-Language": accept_language} if accept_language else {}
                    ),
                )
                page = await context.new_page()
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000
                )
                await _settle(page)
                # Read after settling, and the URL last of the three: a page that routes in the
                # browser changes its address as part of building itself.
                body = await page.content()
                return _PageResult(
                    status_code=response.status if response else 0,
                    final_url=page.url,
                    body=body,
                    state=await context.storage_state(),
                )
            finally:
                await browser.close()
        finally:
            await playwright.stop()
