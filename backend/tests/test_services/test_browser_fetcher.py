"""Pinging a site through a real browser."""

from lifeline.config import Settings
from lifeline.services.browser.fetcher import BrowserFetcher
from lifeline.services.browser.manager import BrowserManager
from tests.conftest import SAMPLE_STATE, FakeDriver, FakeProcesses, make_site


def build(settings: Settings, driver: FakeDriver) -> BrowserFetcher:
    return BrowserFetcher(BrowserManager(settings, driver, FakeProcesses()))


class TestBrowserFetcher:
    async def test_reports_what_the_page_returned(
        self, settings: Settings, fake_driver: FakeDriver
    ) -> None:
        result = await build(settings, fake_driver).fetch(make_site(
            ), SAMPLE_STATE, accept_language="en"
        )

        assert result.status_code == 200
        assert result.final_url == "https://example.org/home"
        assert "Logged in as jure" in result.body

    async def test_sees_no_rotation_when_nothing_changed(
        self, settings: Settings, fake_driver: FakeDriver
    ) -> None:
        result = await build(settings, fake_driver).fetch(make_site(
            ), SAMPLE_STATE, accept_language="en"
        )

        assert result.rotated is False

    async def test_notices_a_changed_cookie_value(
        self, settings: Settings, fake_driver: FakeDriver
    ) -> None:
        # A browser folds Set-Cookie into its own jar as it navigates, so rotation shows up as
        # a difference between what went in and what came back.
        rotated = {
            "cookies": [{**SAMPLE_STATE["cookies"][0], "value": "rotated"}],
            "origins": [],
        }

        async def fetch(url, state, user_agent, *, timeout_seconds, accept_language=None):
            class Result:
                status_code = 200
                final_url = url
                body = "ok"

            result = Result()
            result.state = rotated
            return result

        fake_driver.fetch = fetch

        result = await build(settings, fake_driver).fetch(make_site(
            ), SAMPLE_STATE, accept_language="en"
        )

        assert result.rotated is True

    async def test_notices_a_new_cookie(
        self, settings: Settings, fake_driver: FakeDriver
    ) -> None:
        extended = {
            "cookies": [
                SAMPLE_STATE["cookies"][0],
                {**SAMPLE_STATE["cookies"][0], "name": "csrf", "value": "z"},
            ],
            "origins": [],
        }

        async def fetch(url, state, user_agent, *, timeout_seconds, accept_language=None):
            class Result:
                status_code = 200
                final_url = url
                body = "ok"

            result = Result()
            result.state = extended
            return result

        fake_driver.fetch = fetch

        result = await build(settings, fake_driver).fetch(make_site(
            ), SAMPLE_STATE, accept_language="en"
        )

        assert result.rotated is True

    async def test_truncates_an_enormous_page(
        self, settings: Settings, fake_driver: FakeDriver
    ) -> None:
        from lifeline.services.checker import MAX_BODY_CHARS

        async def fetch(url, state, user_agent, *, timeout_seconds, accept_language=None):
            class Result:
                status_code = 200
                final_url = url
                body = "x" * (MAX_BODY_CHARS + 100)

            result = Result()
            result.state = state
            return result

        fake_driver.fetch = fetch

        result = await build(settings, fake_driver).fetch(make_site(
            ), SAMPLE_STATE, accept_language="en"
        )

        assert len(result.body) == MAX_BODY_CHARS


class TestExtensionArgs:
    def test_names_the_directory_twice(self, data_dir) -> None:
        # --load-extension adds this one; --disable-extensions-except stops Chromium loading
        # anything else it finds in the profile.
        from lifeline.services.browser.driver import extension_args

        args = extension_args(data_dir)

        assert args == [
            f"--disable-extensions-except={data_dir}",
            f"--load-extension={data_dir}",
        ]

    def test_asks_for_nothing_when_there_is_no_extension(self) -> None:
        from lifeline.services.browser.driver import extension_args

        assert extension_args(None) == []

    def test_ignores_a_directory_that_is_not_there(self, data_dir) -> None:
        # A login has to remain possible without it, so an absent directory is not fatal.
        from lifeline.services.browser.driver import extension_args

        assert extension_args(data_dir / "absent") == []
