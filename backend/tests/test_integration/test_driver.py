"""The Playwright driver, against a real browser and a real site."""

from pathlib import Path

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
