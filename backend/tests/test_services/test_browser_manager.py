"""The lifetime of an interactive login session."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from lifeline.config import Settings
from lifeline.services.browser.manager import (
    BrowserManager,
    BrowserUnavailable,
    NoSuchLoginSession,
)
from tests.conftest import SAMPLE_STATE, FakeDriver, FakeProcesses

LOGIN_URL = "https://example.org/login.php"
IDLE = timedelta(minutes=15)


def build(settings: Settings, driver: FakeDriver, processes: FakeProcesses) -> BrowserManager:
    return BrowserManager(settings, driver, processes)


class TestOpening:
    async def test_starts_an_x_server_and_a_vnc_server(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)

        session = await manager.open_login(1, LOGIN_URL, IDLE)

        assert [process.name for process in fake_processes.started] == ["Xvfb", "x11vnc"]
        assert session.display == f":{settings.display_base}"
        assert fake_driver.opened[0][2] == LOGIN_URL

    async def test_waits_for_the_display_before_opening_the_browser(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        # Chromium exits at once if its display is not up, reporting only that it closed.
        await build(settings, fake_driver, fake_processes).open_login(1, LOGIN_URL, IDLE)

        assert fake_processes.displays_waited == [f":{settings.display_base}"]

    async def test_binds_the_vnc_server_to_the_loopback_interface(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        # The API bridges the stream, so nothing outside the container ever dials this port —
        # which is why it can run without a VNC password.
        await build(settings, fake_driver, fake_processes).open_login(1, LOGIN_URL, IDLE)

        x11vnc = fake_processes.started[1]
        assert "-localhost" in x11vnc.argv

    async def test_gives_each_session_an_unguessable_token(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)

        first = await manager.open_login(1, LOGIN_URL, IDLE)
        second = await manager.open_login(2, LOGIN_URL, IDLE)

        assert first.token != second.token
        assert len(first.token) > 20

    async def test_uses_a_profile_directory_per_site(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)

        await manager.open_login(7, LOGIN_URL, IDLE)

        assert fake_driver.opened[0][0] == settings.profiles_dir / "7"

    async def test_opening_a_second_session_closes_the_first(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        # A headful browser is the most expensive thing here, and nobody logs into two sites
        # at once.
        manager = build(settings, fake_driver, fake_processes)
        first = await manager.open_login(1, LOGIN_URL, IDLE)

        await manager.open_login(2, LOGIN_URL, IDLE)

        assert all(process.stopped for process in fake_processes.started[:2])
        assert len(fake_processes.running) == 2
        with pytest.raises(NoSuchLoginSession):
            manager.get(first.token)

    async def test_refuses_when_the_browser_is_disabled(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        settings.browser_enabled = False

        with pytest.raises(BrowserUnavailable):
            await build(settings, fake_driver, fake_processes).open_login(1, LOGIN_URL, IDLE)


class TestFailedOpen:
    async def test_stops_the_x_server_when_the_vnc_server_will_not_start(
        self, settings: Settings, fake_driver: FakeDriver
    ) -> None:
        # A half-started session must not be left holding a display.
        processes = FakeProcesses(fail_on="x11vnc")

        with pytest.raises(OSError):
            await build(settings, fake_driver, processes).open_login(1, LOGIN_URL, IDLE)

        assert processes.running == []

    async def test_stops_everything_when_the_browser_will_not_start(
        self, settings: Settings, fake_processes: FakeProcesses
    ) -> None:
        driver = FakeDriver(fail=True)

        with pytest.raises(RuntimeError):
            await build(settings, driver, fake_processes).open_login(1, LOGIN_URL, IDLE)

        assert fake_processes.running == []

    async def test_leaves_no_session_behind_after_a_failure(
        self, settings: Settings, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, FakeDriver(fail=True), fake_processes)

        with pytest.raises(RuntimeError):
            await manager.open_login(1, LOGIN_URL, IDLE)

        assert manager.active is None


class TestTokens:
    async def test_finds_the_open_session(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)
        session = await manager.open_login(1, LOGIN_URL, IDLE)

        assert manager.get(session.token) is session

    async def test_rejects_an_unknown_token(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)
        await manager.open_login(1, LOGIN_URL, IDLE)

        with pytest.raises(NoSuchLoginSession):
            manager.get("not-the-token")

    async def test_rejects_any_token_when_nothing_is_open(self, settings: Settings) -> None:
        with pytest.raises(NoSuchLoginSession):
            build(settings, FakeDriver(), FakeProcesses()).get("anything")


class TestCapture:
    async def test_reads_the_session_out_of_the_live_browser(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)
        session = await manager.open_login(1, LOGIN_URL, IDLE)

        state, user_agent = await manager.capture(session.token)

        assert state == SAMPLE_STATE
        # The agent is captured with the session because a Cloudflare clearance cookie is
        # bound to the one that earned it.
        assert user_agent == "FakeAgent/1"

    async def test_rejects_an_unknown_token(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)
        await manager.open_login(1, LOGIN_URL, IDLE)

        with pytest.raises(NoSuchLoginSession):
            await manager.capture("wrong")


class TestClosing:
    async def test_stops_every_process_and_closes_the_browser(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)
        await manager.open_login(1, LOGIN_URL, IDLE)

        await manager.close()

        assert fake_processes.running == []
        assert fake_driver.browser.closed is True
        assert manager.active is None

    async def test_reaps_the_browsers_own_children(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        # Playwright's processes are in nobody's process group, so they are matched by the
        # profile directory they were started with.
        manager = build(settings, fake_driver, fake_processes)
        await manager.open_login(3, LOGIN_URL, IDLE)

        await manager.close()

        assert (str(settings.profiles_dir / "3"),) in fake_processes.reaped

    async def test_finishes_the_teardown_even_if_the_browser_will_not_close(
        self, settings: Settings, fake_processes: FakeProcesses
    ) -> None:
        # Otherwise a browser that hangs on close leaves an X server running for ever.
        driver = FakeDriver()

        async def refuse() -> None:
            raise RuntimeError("the browser is wedged")

        manager = build(settings, driver, fake_processes)
        await manager.open_login(1, LOGIN_URL, IDLE)
        driver.browser.close = refuse

        await manager.close()

        assert fake_processes.running == []
        assert manager.active is None

    async def test_closing_nothing_is_harmless(self, settings: Settings) -> None:
        await build(settings, FakeDriver(), FakeProcesses()).close()

    async def test_reaps_orphans_from_a_previous_run(
        self, settings: Settings, fake_processes: FakeProcesses
    ) -> None:
        # A container killed rather than shut down leaves a browser holding a profile
        # directory, which stops the next login from opening it.
        manager = build(settings, FakeDriver(), fake_processes)

        await manager.reap_orphans()

        assert fake_processes.reaped == [
            (str(settings.profiles_dir), f"Xvfb :{settings.display_base}")
        ]


class TestIdleExpiry:
    async def test_closes_a_session_nobody_is_using(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)
        await manager.open_login(1, LOGIN_URL, timedelta(milliseconds=10))

        await asyncio.sleep(0.2)

        assert manager.active is None
        assert fake_processes.running == []

    async def test_a_viewer_keeps_the_session_open(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        # A tab left open is not an abandoned session; closing it mid-login would lose the work.
        manager = build(settings, fake_driver, fake_processes)
        session = await manager.open_login(1, LOGIN_URL, timedelta(milliseconds=10))

        manager.add_viewer(session)
        await asyncio.sleep(0.2)

        assert manager.active is session

    async def test_the_hard_deadline_ends_even_a_watched_session(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        # What stops a forgotten tab holding a browser and an X server indefinitely.
        manager = build(settings, fake_driver, fake_processes)
        session = await manager.open_login(1, LOGIN_URL, timedelta(milliseconds=10))
        manager.add_viewer(session)

        session.hard_deadline = datetime.now(UTC) + timedelta(milliseconds=10)
        await asyncio.sleep(0.3)

        assert manager.active is None

    async def test_the_idle_clock_restarts_when_the_last_viewer_leaves(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)
        session = await manager.open_login(1, LOGIN_URL, timedelta(seconds=30))
        manager.add_viewer(session)

        manager.remove_viewer(session)

        assert session.viewers == 0
        assert session.expires_at > datetime.now(UTC)

    async def test_a_viewer_count_never_goes_negative(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)
        session = await manager.open_login(1, LOGIN_URL, IDLE)

        manager.remove_viewer(session)

        assert session.viewers == 0

    async def test_closing_by_hand_cancels_the_watchdog(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        manager = build(settings, fake_driver, fake_processes)
        session = await manager.open_login(1, LOGIN_URL, timedelta(seconds=30))

        await manager.close()
        await asyncio.sleep(0)

        assert session.watchdog.cancelled() or session.watchdog.done()


class TestBrowserFetch:
    async def test_refuses_when_the_browser_is_disabled(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        settings.browser_enabled = False

        with pytest.raises(BrowserUnavailable):
            await build(settings, fake_driver, fake_processes).fetch(
                "https://example.org/", SAMPLE_STATE, None
            )

    async def test_loads_the_page_through_the_driver(
        self, settings: Settings, fake_driver: FakeDriver, fake_processes: FakeProcesses
    ) -> None:
        result = await build(settings, fake_driver, fake_processes).fetch(
            "https://example.org/home", SAMPLE_STATE, "Agent/1"
        )

        assert result.status_code == 200
        assert fake_driver.fetched == ["https://example.org/home"]
