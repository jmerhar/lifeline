"""SPIKE: does a login actually complete through the proxy, and is the session usable after?

Against a local site that behaves like the server-rendered logins this tool exists for: a form, a
stylesheet, a session cookie, a redirect, and a page that only renders when logged in. Then the same
site again with the form submitted over XHR, which is the case the proxy is expected to fail.

The verdict these tests produce is recorded in docs/proxy-login-spike.md.
"""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import httpx
import pytest

from lifeline.services.proxy import LoginProxy, origin_of

LOGIN_FORM = b"""<!doctype html><html><head><link rel="stylesheet" href="/style.css"></head>
<body><h1>Sign in</h1>
<form method="post" action="/login">
  <input name="username"><input type="password" name="password">
  <button type="submit">Sign in</button>
</form>
<img src="/logo.png"></body></html>"""

XHR_FORM = b"""<!doctype html><html><body><form id="f"><input name="username">
<input type="password" name="password"></form>
<script>
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  await fetch('/api/login', {method: 'POST', body: new FormData(e.target)});
});
</script></body></html>"""


class Site(BaseHTTPRequestHandler):
    """A site with a server-rendered login, and an XHR one beside it."""

    protocol_version = "HTTP/1.1"

    def _send(self, status: int, body: bytes, content_type: str, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The kind of header a real site sends that would stop a proxied page working.
        self.send_header("Content-Security-Policy", "default-src 'self'")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - the name the server dispatches to
        cookies = self.headers.get("Cookie", "")
        if self.path == "/style.css":
            self._send(200, b"body{background:url(/bg.png)}", "text/css")
        elif self.path in ("/logo.png", "/bg.png"):
            self._send(200, b"\x89PNG\r\n", "image/png")
        elif self.path == "/login":
            self._send(200, LOGIN_FORM, "text/html")
        elif self.path == "/login-xhr":
            self._send(200, XHR_FORM, "text/html")
        elif self.path == "/home":
            if "session=granted" in cookies:
                self._send(200, b"<html>Logged in as jure. Log out</html>", "text/html")
            else:
                self._send(302, b"", "text/html", Location="/login")
        else:
            self._send(404, b"nope", "text/html")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode())
        good = form.get("username") == ["jure"] and form.get("password") == ["s3cret"]
        if self.path == "/login" and good:
            self._send(
                302, b"", "text/html", Location="/home", Set_Cookie="session=granted; Path=/"
            )
        elif self.path == "/api/login" and good:
            self._send(200, b'{"ok":true}', "application/json", Set_Cookie="session=granted; Path=/")
        else:
            self._send(200, LOGIN_FORM, "text/html")

    def log_message(self, *_: object) -> None:
        """Keep the test output readable."""


@pytest.fixture
def site() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


PREFIX = "/login/1"


class TestServerRenderedLogin:
    """The shape most of the sites this tool is for actually have."""

    async def test_the_form_arrives_pointing_back_through_lifeline(self, site: str) -> None:
        proxy = LoginProxy(user_agent="lifeline-spike/1")

        page = await proxy.forward(origin=site, path="/login", prefix=PREFIX)

        body = page.body.decode()
        assert page.status_code == 200
        assert f'action="{PREFIX}/login"' in body
        assert f'href="{PREFIX}/style.css"' in body
        assert f'src="{PREFIX}/logo.png"' in body

    async def test_the_stylesheet_is_rewritten_too(self, site: str) -> None:
        proxy = LoginProxy(user_agent="lifeline-spike/1")

        css = await proxy.forward(origin=site, path="/style.css", prefix=PREFIX)

        assert f"url({PREFIX}/bg.png)" in css.body.decode()

    async def test_the_policy_that_would_block_it_is_dropped(self, site: str) -> None:
        # Worth seeing plainly: this only works by removing a protection the site asked for.
        proxy = LoginProxy(user_agent="lifeline-spike/1")

        page = await proxy.forward(origin=site, path="/login", prefix=PREFIX)

        assert "content-security-policy" not in {k.lower() for k in page.headers}

    async def test_submitting_the_form_logs_in(self, site: str) -> None:
        proxy = LoginProxy(user_agent="lifeline-spike/1")

        submitted = await proxy.forward(
            origin=site,
            path="/login",
            prefix=PREFIX,
            method="POST",
            body=b"username=jure&password=s3cret",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        assert submitted.status_code == 302
        # The redirect points back through lifeline, so the browser stays inside the proxy.
        assert submitted.headers["location"] == f"{PREFIX}/home"

    async def test_the_session_cookie_is_kept_and_never_handed_to_the_browser(
        self, site: str
    ) -> None:
        proxy = LoginProxy(user_agent="lifeline-spike/1")

        submitted = await proxy.forward(
            origin=site,
            path="/login",
            prefix=PREFIX,
            method="POST",
            body=b"username=jure&password=s3cret",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        assert proxy.cookies.get("session") == "granted"
        assert "set-cookie" not in {k.lower() for k in submitted.headers}

    async def test_the_captured_session_works_on_its_own_afterwards(self, site: str) -> None:
        # The point of the whole exercise: what lifeline keeps has to be a session it can ping with,
        # with no proxy and no browser involved.
        proxy = LoginProxy(user_agent="lifeline-spike/1")
        await proxy.forward(
            origin=site,
            path="/login",
            prefix=PREFIX,
            method="POST",
            body=b"username=jure&password=s3cret",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        async with httpx.AsyncClient(cookies=proxy.cookies, follow_redirects=True) as client:
            response = await client.get(f"{site}/home")

        assert response.status_code == 200
        assert "Logged in as jure" in response.text


class TestXhrLogin:
    """The shape the proxy cannot handle, demonstrated rather than assumed."""

    async def test_the_url_javascript_builds_is_left_alone(self, site: str) -> None:
        proxy = LoginProxy(user_agent="lifeline-spike/1")

        page = await proxy.forward(origin=site, path="/login-xhr", prefix=PREFIX)

        body = page.body.decode()
        # Still bare. In a browser it resolves against lifeline's own root, so the submission goes to
        # lifeline's /api/login — which is lifeline's API, not the site's.
        assert "fetch('/api/login'" in body
        assert f"{PREFIX}/api/login" not in body


class TestOrigin:
    def test_reads_the_scheme_and_host(self) -> None:
        assert origin_of("https://site.example/login.php?x=1") == "https://site.example"
