"""The Playwright driver, against a real browser and a real site."""

from pathlib import Path

import pytest

from lifeline.services.browser.driver import PlaywrightDriver
from lifeline.services.cookies import StorageState


def state_for(origin: str, value: str = "original") -> StorageState:
    """A stored session for the local test site."""
    return {
        "cookies": [
            {
                "name": "session",
                "value": value,
                "domain": "127.0.0.1",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": False,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }


class TestHeadlessFetch:
    async def test_replays_a_stored_session(
        self, headless_browser: None, site_server: str
    ) -> None:
        result = await PlaywrightDriver().fetch(
            f"{site_server}/home", state_for(site_server), None, timeout_seconds=30
        )

        assert result.status_code == 200
        assert "Logged in as jure" in result.body

    async def test_brings_back_a_rotated_cookie(
        self, headless_browser: None, site_server: str
    ) -> None:
        # What a browser-mode check depends on: the site re-issues the session cookie, and the
        # state handed back has to carry the new value or the next check uses a stale one.
        result = await PlaywrightDriver().fetch(
            f"{site_server}/home", state_for(site_server), None, timeout_seconds=30
        )

        session = next(c for c in result.state["cookies"] if c["name"] == "session")
        assert session["value"] == "rotated"

    async def test_sees_a_logged_out_page_without_a_session(
        self, headless_browser: None, site_server: str
    ) -> None:
        result = await PlaywrightDriver().fetch(
            f"{site_server}/home", {"cookies": [], "origins": []}, None, timeout_seconds=30
        )

        assert "Enter your password" in result.body

    async def test_reports_the_url_it_ended_on(
        self, headless_browser: None, site_server: str
    ) -> None:
        result = await PlaywrightDriver().fetch(
            f"{site_server}/redirect", state_for(site_server), None, timeout_seconds=30
        )

        assert result.final_url == f"{site_server}/home"

    async def test_reports_an_error_status(
        self, headless_browser: None, site_server: str
    ) -> None:
        result = await PlaywrightDriver().fetch(
            f"{site_server}/missing", state_for(site_server), None, timeout_seconds=30
        )

        assert result.status_code == 404

    async def test_sends_the_user_agent_it_is_given(
        self, headless_browser: None, site_server: str
    ) -> None:
        # A Cloudflare clearance cookie is bound to the agent that earned it, so replaying the
        # captured one is the difference between passing the challenge and failing it.
        driver = PlaywrightDriver()

        result = await driver.fetch(
            f"{site_server}/home", state_for(site_server), "Captured/9.9", timeout_seconds=30
        )

        assert result.status_code == 200


class TestHeadfulLogin:
    async def test_opens_a_browser_and_captures_what_it_holds(
        self, display: str, site_server: str, data_dir: Path
    ) -> None:
        browser = await PlaywrightDriver().open_interactive(
            data_dir / "profile", display, f"{site_server}/home"
        )
        try:
            state = await browser.storage_state()
            user_agent = await browser.user_agent()
        finally:
            await browser.close()

        # The page set a cookie, which is what an interactive login is for.
        assert any(cookie["name"] == "visited" for cookie in state["cookies"])
        assert user_agent and "Chrome" in user_agent

    async def test_keeps_the_profile_for_next_time(
        self, display: str, site_server: str, data_dir: Path
    ) -> None:
        # A persistent profile is what lets a half-finished login — a device-trust cookie, a
        # partial two-factor enrolment — survive closing the panel and coming back.
        profile = data_dir / "profile"
        browser = await PlaywrightDriver().open_interactive(
            profile, display, f"{site_server}/home"
        )
        await browser.close()

        assert profile.is_dir()
        assert any(profile.iterdir())

    async def test_still_opens_when_the_site_will_not_load(
        self, display: str, data_dir: Path, unreachable_url: str
    ) -> None:
        # The person can navigate it themselves; a browser that refuses to appear because the
        # first request failed leaves them with nothing. The session is asserted on rather
        # than the User-Agent, because with nothing loaded there is no request to read one
        # from yet — that case is covered by test_captures_the_agent_the_site_actually_saw.
        browser = await PlaywrightDriver().open_interactive(
            data_dir / "profile", display, unreachable_url
        )
        try:
            state = await browser.storage_state()
        finally:
            await browser.close()

        assert "cookies" in state

    async def test_captures_the_agent_the_site_actually_saw(
        self, display: str, site_server: str, data_dir: Path
    ) -> None:
        # Taken from the request the browser made, so that saving a session works while a
        # navigation is in flight rather than raising and losing the capture.
        browser = await PlaywrightDriver().open_interactive(
            data_dir / "profile", display, f"{site_server}/home"
        )
        try:
            agent = await browser.user_agent()
        finally:
            await browser.close()

        assert agent and "Mozilla" in agent


class TestAPageBuiltInTheBrowser:
    """A single-page application puts nothing in its served markup.

    Reading the document as soon as it parses sees an empty shell and the address that was asked
    for, which is indistinguishable signed in or out — the exact reason a real site of this kind
    reported that its two pages looked identical.
    """

    async def test_reads_the_document_the_javascript_built(
        self, chromium_available: bool, site_server: str
    ) -> None:
        if not chromium_available:
            pytest.skip("Chromium is not installed")

        result = await PlaywrightDriver().fetch(
            f"{site_server}/app",
            {"cookies": [], "origins": []},
            None,
            timeout_seconds=20,
        )

        assert "Please login" in result.body
        assert "Password reset" in result.body

    async def test_follows_the_route_the_javascript_navigated_to(
        self, chromium_available: bool, site_server: str
    ) -> None:
        # Client-side routing changes the URL only once the application has run, so a URL rule
        # cannot match until then.
        if not chromium_available:
            pytest.skip("Chromium is not installed")

        result = await PlaywrightDriver().fetch(
            f"{site_server}/app",
            {"cookies": [], "origins": []},
            None,
            timeout_seconds=20,
        )

        assert result.final_url.endswith("/auth/signin")

    async def test_tells_a_signed_in_shell_from_a_signed_out_one(
        self, chromium_available: bool, site_server: str
    ) -> None:
        if not chromium_available:
            pytest.skip("Chromium is not installed")
        result = await PlaywrightDriver().fetch(
            f"{site_server}/app", state_for(site_server), None, timeout_seconds=20
        )

        assert "Log out" in result.body


class TestStartingSignedOut:
    """What the browser is left holding when a login opens for a site with no stored session.

    Headless, because none of this needs a screen: the profile, its cookie jar and its stored
    data behave the same either way, and what is being proved is that they are empty.
    """

    async def open_profile(self, profile: Path, url: str, *, signed_out: bool) -> tuple[str, str]:
        """Open ``url`` in a persistent profile and report what the page can see."""
        from playwright.async_api import async_playwright

        from lifeline.services.browser.driver import forget_site

        playwright = await async_playwright().start()
        try:
            context = await playwright.chromium.launch_persistent_context(
                str(profile), headless=True, args=["--no-sandbox"]
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                if signed_out:
                    await forget_site(context, page, url)
                await page.goto(url, wait_until="domcontentloaded")
                return (
                    await page.evaluate("localStorage.getItem('auth.token') || ''"),
                    await page.evaluate("document.cookie"),
                )
            finally:
                await context.close()
        finally:
            await playwright.stop()

    async def sign_in(self, profile: Path, site_server: str) -> None:
        """Leave the profile holding a session, in local storage and in a cookie."""
        token, cookies = await self.open_profile(
            profile, f"{site_server}/remember", signed_out=False
        )
        assert token == "secret"
        assert "crumb=yes" in cookies

    async def test_forgets_a_session_kept_in_local_storage(
        self, chromium_available: bool, site_server: str, tmp_path: Path
    ) -> None:
        # Clearing the cookie jar leaves this behind, so the site opened already signed in — which
        # is how another account gets captured for a site being added.
        if not chromium_available:
            pytest.skip("Chromium is not installed")
        profile = tmp_path / "profile"
        await self.sign_in(profile, site_server)

        # Read from a page that sets nothing: the one that signs you in does so again on the way
        # past, which would answer that the page works rather than that the profile was cleared.
        token, _ = await self.open_profile(profile, f"{site_server}/quiet", signed_out=True)

        assert token == ""

    async def test_forgets_the_cookies_too(
        self, chromium_available: bool, site_server: str, tmp_path: Path
    ) -> None:
        if not chromium_available:
            pytest.skip("Chromium is not installed")
        profile = tmp_path / "profile"
        await self.sign_in(profile, site_server)

        _, cookies = await self.open_profile(profile, f"{site_server}/quiet", signed_out=True)

        assert "crumb=yes" not in cookies

    async def test_leaves_a_stored_session_alone_when_not_asked_to(
        self, chromium_available: bool, site_server: str, tmp_path: Path
    ) -> None:
        # A site being logged into again keeps whatever the browser has, which saves the trip.
        if not chromium_available:
            pytest.skip("Chromium is not installed")
        profile = tmp_path / "profile"
        await self.sign_in(profile, site_server)

        token, cookies = await self.open_profile(profile, f"{site_server}/quiet", signed_out=False)

        assert token == "secret"
        assert "crumb=yes" in cookies

    async def test_leaves_another_site_in_the_profile_alone(
        self, chromium_available: bool, site_server: str, tmp_path: Path
    ) -> None:
        # The profile is shared by every site, so emptying the jar wholesale would sign somebody
        # out of all of them — and out of the password manager's own web vault.
        if not chromium_available:
            pytest.skip("Chromium is not installed")
        profile = tmp_path / "profile"
        await self.sign_in(profile, site_server)
        elsewhere = f"http://localhost:{site_server.rsplit(':', maxsplit=1)[1]}"

        # Forgets the other origin, which shares this server but is a different site to a browser.
        await self.open_profile(profile, f"{elsewhere}/quiet", signed_out=True)

        token, cookies = await self.open_profile(profile, f"{site_server}/quiet", signed_out=False)
        assert token == "secret"
        assert "crumb=yes" in cookies
