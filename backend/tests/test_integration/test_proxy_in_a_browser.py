"""SPIKE: the half that matters — does a login through the proxy work in a real browser?

The server-side tests prove the rewriting and the capture. This drives the same flow the way a person
would: a real browser loads the site's login page *through lifeline*, a password manager's job is done
by filling the fields, the form is submitted, and lifeline is then asked whether what it captured is a
working session.

Skipped unless Chromium is installed. This is the test whose result decides the spike.
"""

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import ThreadingHTTPServer

import httpx
import pytest
import uvicorn

from lifeline.api.app import create_app
from lifeline.api.security import hash_password
from lifeline.models import Base, Site, User
from lifeline.services.crypto import Cipher

from .test_proxy_spike import Site as SiteHandler


@pytest.fixture
def target_site() -> Iterator[str]:
    """The site being logged into."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), SiteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
async def lifeline(settings, target_site: str) -> AsyncIterator[tuple[str, object]]:
    """lifeline itself, served over a real port so a browser can reach it."""
    from lifeline.db import create_engine, create_sessionmaker

    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_sessionmaker(engine)
    async with factory() as session:
        session.add(User(username="a", password_hash=hash_password("a-good-long-password")))
        session.add(
            Site(
                name="target",
                ping_url=f"{target_site}/home",
                login_url=f"{target_site}/login",
                success_pattern="Logged in as",
            )
        )
        await session.commit()

    app = create_app(settings)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", factory
    finally:
        server.should_exit = True
        await task
        await engine.dispose()


class TestLoginThroughTheProxyInABrowser:
    async def test_a_browser_can_log_in_and_lifeline_keeps_a_working_session(
        self, headless_browser: None, lifeline: tuple[str, object], target_site: str, settings
    ) -> None:
        from playwright.async_api import async_playwright

        base, factory = lifeline
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            try:
                # Log into lifeline first: the proxy is behind its authentication.
                await page.goto(f"{base}/api/health")
                response = await page.request.post(
                    f"{base}/api/auth/login",
                    data={"username": "a", "password": "a-good-long-password"},
                )
                assert response.ok

                # The site's login page, served through lifeline, in a real browser.
                await page.goto(f"{base}/api/login-proxy/1/login")
                assert await page.locator("h1").inner_text() == "Sign in"

                # What a password manager would do.
                await page.fill("input[name=username]", "jure")
                await page.fill("input[name=password]", "s3cret")
                await page.click("button[type=submit]")
                await page.wait_for_load_state("networkidle")

                # The redirect kept the browser inside the proxy, and the protected page rendered.
                assert "/api/login-proxy/1/home" in page.url
                assert "Logged in as jure" in await page.content()

                # Ask lifeline to keep it, then check what it kept actually works.
                captured = await page.request.post(f"{base}/api/login-proxy/1/finish")
                assert captured.ok, await captured.text()
            finally:
                await context.close()
                await browser.close()

        async with factory() as session:
            site = await session.get(Site, 1)
            state = Cipher.from_settings(settings).decrypt_json(site.session.state)

        from lifeline.services.cookies import state_to_jar

        async with httpx.AsyncClient(cookies=state_to_jar(state), follow_redirects=True) as client:
            direct = await client.get(f"{target_site}/home")

        assert direct.status_code == 200
        assert "Logged in as jure" in direct.text

    async def test_the_proxied_page_can_call_lifelines_own_api(
        self, headless_browser: None, lifeline: tuple[str, object]
    ) -> None:
        """The finding that decides how this would have to be deployed.

        A proxied page is served from lifeline's origin, so its JavaScript is same-origin with
        lifeline's API — and the session cookie is sent with a same-origin fetch whether it is
        HttpOnly or not. Any script on a site's login page can therefore read and change everything
        lifeline holds, including the notification settings, which carry a credential.

        This asserts the hole exists, so that it cannot be fixed by accident and unnoticed.
        """
        from playwright.async_api import async_playwright

        base, _ = lifeline
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context()
            page = await context.new_page()
            try:
                await page.goto(f"{base}/api/health")
                await page.request.post(
                    f"{base}/api/auth/login",
                    data={"username": "a", "password": "a-good-long-password"},
                )
                await page.goto(f"{base}/api/login-proxy/1/login")

                reached = await page.evaluate(
                    """async () => {
                        const response = await fetch('/api/sites', {credentials: 'same-origin'});
                        return {status: response.status, sites: (await response.json()).length};
                    }"""
                )
            finally:
                await context.close()
                await browser.close()

        assert reached["status"] == 200
        assert reached["sites"] >= 1
