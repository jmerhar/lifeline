"""Fixtures for the tests that drive a real browser.

These are the only tests that need Chromium on disk. They are skipped rather than failed
when it is absent, so a clone without `playwright install chromium` still has a green
suite — and so that what they prove (that the real driver works) is never quietly replaced
by a stand-in.
"""

import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

# A display to run the headful browser on. Set in CI after starting Xvfb; unset locally,
# where opening a real browser window in the middle of a test run is unwelcome.
DISPLAY_ENV = "LIFELINE_TEST_DISPLAY"

LOGGED_IN_BODY = b"<html><body>Logged in as jure. <a href='/logout'>Log out</a></body></html>"
LOGGED_OUT_BODY = b"<html><body><form>Enter your password</form></body></html>"

# An empty shell that builds its page in the browser and then changes the URL, the way a
# single-page application does. Nothing here is in the served markup: a fetch that reads the
# document as soon as it parses sees an empty <div> and the address it asked for.
#
# Every phrase is assembled from fragments so that none of them appears in the markup as it is
# served. A page's own source is part of what a fetch returns, so a test looking for text the
# script mentions passes without the script ever having run — which is how two of these first
# went green against a driver that could not see rendered content at all.
#
# The delay stands in for the cost of a real framework starting up — fetching and parsing its
# bundle, deciding whether there is a session, and only then routing. A shorter one is passed by
# accident, which is how this went unnoticed: the difference appears late, not immediately.
SHELL_BODY = b"""<html><body><div id="app"></div><script>
setTimeout(function () {
  var signedIn = document.cookie.indexOf('session=') !== -1;
  var words = signedIn
    ? ['Log', 'ged in as jure. Log ', 'out']
    : ['Please log', 'in. Pass', 'word reset'];
  document.getElementById('app').textContent = words.join('');
  if (!signedIn) history.pushState({}, '', '/auth/signin');
}, 1500);
</script></body></html>"""


class SiteHandler(BaseHTTPRequestHandler):
    """A site that tells logged-in from logged-out by cookie, and rotates its session.

    Rotation is the behaviour worth exercising against a real browser: the response re-issues
    the session cookie, and what the browser hands back afterwards has to carry the new value.
    """

    def do_GET(self) -> None:  # noqa: N802 - the name BaseHTTPRequestHandler dispatches to
        cookies = self.headers.get("Cookie", "")
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/home")
            self.end_headers()
            return
        if self.path == "/missing":
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>no such page</html>")
            return

        if self.path.startswith("/app") or self.path == "/auth/signin":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(SHELL_BODY)
            return

        logged_in = "session=original" in cookies or "session=rotated" in cookies
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        if logged_in:
            self.send_header("Set-Cookie", "session=rotated; Path=/")
        else:
            self.send_header("Set-Cookie", "visited=yes; Path=/")
        self.end_headers()
        self.wfile.write(LOGGED_IN_BODY if logged_in else LOGGED_OUT_BODY)

    def log_message(self, *_: object) -> None:
        """Keep the test output readable."""


@pytest.fixture
def site_server() -> Iterator[str]:
    """A local site, served from a thread so a separate browser process can reach it."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), SiteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def chromium_available() -> bool:
    """Whether a Chromium that Playwright can drive is installed."""
    import asyncio

    async def probe() -> bool:
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            await browser.close()
            return True
        except Exception:
            return False
        finally:
            await playwright.stop()

    return asyncio.run(probe())


@pytest.fixture
def headless_browser(chromium_available: bool) -> None:
    """Skip unless a browser is installed."""
    if not chromium_available:
        pytest.skip("Chromium is not installed; run `playwright install chromium`")


@pytest.fixture
def display(headless_browser: None) -> str:
    """The display for a headful browser, or a skip when there is none."""
    value = os.environ.get(DISPLAY_ENV)
    if not value:
        pytest.skip(f"set {DISPLAY_ENV} to an X display to run the headful tests")
    return value


@pytest.fixture
def unreachable_url() -> str:
    """A URL that will not connect.

    A high closed port rather than a low one: Chromium refuses ports like 1 outright with
    ERR_UNSAFE_PORT, which is a different failure from the site being down.
    """
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/nothing-here"
